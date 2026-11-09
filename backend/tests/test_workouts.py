from datetime import date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.coach.plan import ProposalBody
from garmin_coach.config import Settings
from garmin_coach.garmin.workouts import WorkoutError, workout_payload
from garmin_coach.metrics.zones import hr_zones
from garmin_coach.models import Plan, PlannedSession, PlanProposal
from garmin_coach.sync import SyncService
from tests.apps import single_app
from tests.garmin_data import FakeGarmin

NOW = datetime(2026, 11, 6, 12, 0)
ZONES = hr_zones(144, 165)

STRENGTH: dict[str, Any] = dict(
    day=date(2026, 11, 10),
    sport="strength",
    kind="strength",
    title="Legs for the mountains",
    duration_min=45,
    exercises=[
        {
            "name": "Back Squat",
            "sets": 3,
            "reps": "5",
            "load": "70 kg",
            "rest_s": 150,
            "warmup_sets": [{"reps": 8, "weight_kg": 20}, {"reps": 5, "weight_kg": 50}],
        },
        {
            "name": "Dumbbell Bulgarian Split Squats",
            "sets": 3,
            "reps": "8/leg",
            "load": "12 kg",
            "rest_s": 90,
        },
        {"name": "Nordic hamstring curl", "sets": 3, "reps": "5", "note": "Slow on the way down"},
        {"name": "Side Plank", "sets": 2, "reps": "30 s/side", "load": "bodyweight", "rest_s": 30},
    ],
)

HILLS: dict[str, Any] = dict(
    day=date(2026, 11, 11),
    sport="run",
    kind="hills",
    title="Hill repeats",
    duration_min=60,
    steps=[
        {"kind": "warmup", "duration_min": 15, "target": "Z1-Z2"},
        {
            "kind": "intervals",
            "repeats": 6,
            "duration_min": 3,
            "grade_pct": 8,
            "target": "Z4",
            "recovery": "2 min jog down",
        },
        {"kind": "cooldown", "duration_min": 10, "target": "Z1"},
    ],
)


def strength_session(**fields: Any) -> PlannedSession:
    return PlannedSession(**({"steps": []} | STRENGTH | fields))


def hills_session(**fields: Any) -> PlannedSession:
    return PlannedSession(**({"exercises": []} | HILLS | fields))


def steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = payload["workoutSegments"][0]["workoutSteps"]
    return found


def orders(nodes: list[dict[str, Any]]) -> list[int]:
    found = []
    for node in nodes:
        found.append(node["stepOrder"])
        found += orders(node.get("workoutSteps", []))
    return found


def test_strength_session_becomes_a_strength_workout() -> None:
    payload = workout_payload(strength_session(), ZONES)
    warmup, bar, bar_rest, ramp, _, squat, split_squat, nordic, plank = steps(payload)

    assert payload["sportType"]["sportTypeKey"] == "strength_training"
    assert payload["estimatedDurationInSecs"] == 2700
    assert sorted(orders(steps(payload))) == list(range(1, 18))

    assert warmup["stepType"]["stepTypeKey"] == "warmup"
    assert warmup["endConditionValue"] == 600
    assert "category" not in warmup

    assert (bar["exerciseName"], bar["endConditionValue"], bar["weightValue"]) == (
        "BACK_SQUATS",
        8,
        20000,
    )
    assert bar["description"] == "Warm-up set"
    assert bar_rest["endCondition"]["conditionTypeKey"] == "lap.button"
    assert ramp["weightValue"] == 50000
    assert squat["numberOfIterations"] == 3
    assert squat["workoutSteps"][0]["weightValue"] == 70000

    assert [block["numberOfIterations"] for block in (split_squat, nordic, plank)] == [3, 3, 2]
    work, rest = split_squat["workoutSteps"]
    assert work["category"] == "LUNGE"
    assert work["exerciseName"] == "DUMBBELL_BULGARIAN_SPLIT_SQUAT"
    assert work["endCondition"]["conditionTypeKey"] == "reps"
    assert work["endConditionValue"] == 8
    assert work["weightValue"] == 12000
    assert work["description"] == "per leg"
    assert rest["endConditionValue"] == 90

    nordic, lap_rest = nordic["workoutSteps"]
    assert nordic["category"] == "TOTAL_BODY"
    assert nordic["description"] == "Nordic hamstring curl. Slow on the way down"
    assert lap_rest["endCondition"]["conditionTypeKey"] == "lap.button"

    plank = plank["workoutSteps"][0]
    assert plank["category"] == "PLANK"
    assert plank["endCondition"]["conditionTypeKey"] == "time"
    assert plank["endConditionValue"] == 30
    assert "weightValue" not in plank


def test_run_steps_get_heart_rate_ranges_from_the_athletes_zones() -> None:
    payload = workout_payload(hills_session(), ZONES)
    warmup, repeats, cooldown = steps(payload)

    assert payload["sportType"]["sportTypeKey"] == "running"
    assert (warmup["targetValueOne"], warmup["targetValueTwo"]) == (40, 144)
    assert repeats["numberOfIterations"] == 6
    work, recovery = repeats["workoutSteps"]
    assert work["endConditionValue"] == 180
    assert (work["targetValueOne"], work["targetValueTwo"]) == (166, 173)
    assert work["description"] == "8% gradient"
    assert recovery["stepType"]["stepTypeKey"] == "recovery"
    assert recovery["endConditionValue"] == 120
    assert cooldown["stepType"]["stepTypeKey"] == "cooldown"


def test_mobility_sessions_get_no_warmup_step() -> None:
    mobility = strength_session(kind="mobility")
    first = steps(workout_payload(mobility, None))[0]
    assert first["stepType"]["stepTypeKey"] == "interval"


def test_run_without_steps_is_one_step_and_rest_days_are_refused() -> None:
    easy = PlannedSession(
        day=date(2026, 11, 12),
        sport="run",
        kind="easy",
        title="Easy",
        distance_km=8,
        intensity="Z2",
    )
    (step,) = steps(workout_payload(easy, None))
    assert step["endCondition"]["conditionTypeKey"] == "distance"
    assert step["endConditionValue"] == 8000
    assert step["zoneNumber"] == 2

    rest = PlannedSession(day=date(2026, 11, 13), sport="rest", kind="rest", title="Rest")
    with pytest.raises(WorkoutError):
        workout_payload(rest, None)


@pytest.fixture
def garmin() -> FakeGarmin:
    return FakeGarmin([])


@pytest.fixture
def client(sessions: sessionmaker[Session], garmin: FakeGarmin) -> TestClient:
    with sessions() as session:
        session.add(
            Plan(
                id=1,
                title="Base",
                start_date=date(2026, 11, 10),
                end_date=date(2026, 11, 13),
                created_at=NOW,
            )
        )
        session.add_all([strength_session(plan_id=1), hills_session(plan_id=1)])
        session.add(
            PlannedSession(
                plan_id=1, day=date(2026, 11, 13), sport="rest", kind="rest", title="Rest"
            )
        )
        session.commit()

    def make_service() -> SyncService:
        return SyncService(garmin, sessions, request_delay=0, sleep=lambda _: None)

    coach = Coach(sessions, None, coach_settings(Settings.model_construct()))
    return TestClient(single_app(sessions, make_service, coach))


def propose(sessions: sessionmaker[Session], body: ProposalBody) -> int:
    with sessions() as session:
        proposal = PlanProposal(
            created_at=NOW,
            summary="Change",
            reason="Test",
            body=body.model_dump_json(),
            status="pending",
        )
        session.add(proposal)
        session.commit()
        return proposal.id


def test_sending_replacing_and_deleting_a_session_on_the_watch(
    client: TestClient, garmin: FakeGarmin
) -> None:
    sent = client.post("/api/sessions/1/watch").json()
    assert sent["sent_to_watch_at"] is not None
    (workout_id,) = garmin.workouts
    assert ("schedule_workout", (workout_id, date(2026, 11, 10))) in garmin.calls

    client.post("/api/sessions/1/watch")
    assert workout_id not in garmin.workouts
    assert ("unschedule_workout", (workout_id + 1000,)) in garmin.calls
    assert len(garmin.workouts) == 1

    refused = client.post("/api/sessions/3/watch")
    assert refused.status_code == 422
    assert "rest" in refused.json()["detail"]

    assert client.delete("/api/sessions/1").status_code == 204
    assert garmin.workouts == {}


def test_accepted_proposals_update_sessions_on_the_watch(
    client: TestClient, garmin: FakeGarmin, sessions: sessionmaker[Session]
) -> None:
    client.post("/api/sessions/1/watch")
    client.post("/api/sessions/2/watch")
    strength_id, hills_id = garmin.workouts

    spec = HILLS | {"day": date(2026, 11, 12)}
    body = ProposalBody.model_validate(
        {
            "changes": [
                {"op": "remove", "session_id": 1},
                {"op": "update", "session_id": 2, "session": spec},
            ]
        }
    )
    proposal_id = propose(sessions, body)
    assert client.post(f"/api/proposals/{proposal_id}/accept").status_code == 200

    assert strength_id not in garmin.workouts
    assert hills_id not in garmin.workouts
    (new_hills_id,) = garmin.workouts
    assert ("schedule_workout", (new_hills_id, date(2026, 11, 12))) in garmin.calls
    with sessions() as session:
        assert session.get_one(PlannedSession, 2).garmin_workout_id == new_hills_id
