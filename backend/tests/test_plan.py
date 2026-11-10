import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.coach.prompt import context_block
from garmin_coach.coach.tools import ToolContext, run_tool
from garmin_coach.config import Settings
from garmin_coach.metrics.compliance import match_sessions, planned_hard_minutes, target_zone
from garmin_coach.metrics.strength import effective_sets
from garmin_coach.models import (
    Activity,
    ActivityHeartRate,
    Plan,
    PlannedSession,
    SessionMatch,
    ThresholdTest,
)
from garmin_coach.normalize import rebuild_all
from garmin_coach.sync import SyncService
from tests.apps import single_app
from tests.garmin_data import FakeGarmin, activity_summary, exercise_sets

NOW = datetime(2026, 10, 30, 12, 0)


def planned(day: str, sport: str, title: str, **targets: float) -> PlannedSession:
    return PlannedSession(
        plan_id=1, day=date.fromisoformat(day), sport=sport, kind="easy", title=title, **targets
    )


@pytest.fixture
def plan(sessions: sessionmaker[Session]) -> sessionmaker[Session]:
    with sessions() as session:
        for activity_id, start, type_key, duration in [
            (10, "2026-10-26 07:00:00", "running", 3000.0),
            (11, "2026-10-26 18:00:00", "running", 1800.0),
            (12, "2026-10-29 07:00:00", "trail_running", 7200.0),
            (13, "2026-10-28 17:00:00", "strength_training", 2700.0),
        ]:
            summary = activity_summary(activity_id, start, type_key=type_key, duration_s=duration)
            raw_store.put_activity(session, activity_id, "summary", summary)
        raw_store.put_activity(session, 13, "exercise_sets", exercise_sets())
        rebuild_all(session)
        session.add(
            Plan(
                id=1,
                title="Base",
                start_date=date(2026, 10, 26),
                end_date=date(2026, 11, 1),
                created_at=NOW,
            )
        )
        session.add_all(
            [
                planned("2026-10-26", "run", "Short run", duration_min=30),
                planned("2026-10-27", "strength", "Strength A", duration_min=45),
                planned("2026-10-28", "run", "Long run", duration_min=120, elevation_gain_m=600),
                planned("2026-10-30", "rest", "Rest"),
            ]
        )
        session.commit()
    return sessions


def test_sessions_match_activities_with_compliance(plan: sessionmaker[Session]) -> None:
    with plan() as session:
        assert match_sessions(session, date(2026, 10, 26), date(2026, 11, 1)) == 3
        session.commit()
        matches = {
            m.planned_session_id: m
            for m in session.query(SessionMatch).order_by(SessionMatch.activity_id)
        }

    assert matches[1].activity_id == 11
    assert matches[1].compliance == 100
    assert matches[2].activity_id == 13
    assert matches[3].activity_id == 12
    assert matches[3].compliance == pytest.approx(75)
    assert 4 not in matches


def test_extra_activity_stays_on_a_day_with_its_own_session(
    plan: sessionmaker[Session],
) -> None:
    with plan() as session:
        session.add(planned("2026-10-27", "run", "Hill repeats", duration_min=60))
        session.commit()
        match_sessions(session, date(2026, 10, 26), date(2026, 11, 1))
        session.commit()
        matched = {m.planned_session_id: m.activity_id for m in session.query(SessionMatch)}

    assert matched[1] == 11
    assert 10 not in matched.values()
    assert 5 not in matched


def test_activity_page_and_set_editor(plan: sessionmaker[Session]) -> None:
    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), plan, request_delay=0, sleep=lambda _: None)

    coach = Coach(plan, None, coach_settings(Settings.model_construct()))
    client = TestClient(single_app(plan, make_service, coach, schedule_sync=False))
    with plan() as session:
        match_sessions(session, date(2026, 10, 26), date(2026, 11, 1))
        session.commit()

    detail = client.get("/api/activities/13").json()
    assert detail["planned"]["title"] == "Strength A"
    assert [s["exercise_name"] for s in detail["sets"]] == [None, "BACK_SQUAT"]
    assert "SQUAT" in detail["exercise_categories"]

    edit = {
        "exercise_category": "LUNGE",
        "exercise_name": "SPLIT_SQUAT",
        "reps": 8,
        "weight_kg": 40,
    }
    sets = client.put("/api/activities/13/sets/1", json=edit).json()
    assert sets[1]["edited"] and sets[1]["exercise_name"] == "SPLIT_SQUAT"
    assert sets[1]["original"]["exercise_name"] == "BACK_SQUAT"
    with plan() as session:
        assert [
            s.name for s in effective_sets(session, date(2026, 10, 28), date(2026, 10, 28))
        ] == [
            None,
            "SPLIT_SQUAT",
        ]

    client.put("/api/activities/13/sets/0", json={"deleted": True})
    with plan() as session:
        assert len(effective_sets(session, date(2026, 10, 28), date(2026, 10, 28))) == 1

    assert client.delete("/api/activities/13/sets/1/edit").status_code == 204
    assert client.get("/api/activities/13").json()["sets"][1]["exercise_name"] == "BACK_SQUAT"
    assert client.get("/api/activities/999").status_code == 404

    calendar = client.get("/api/plan", params={"start": "2026-10-26", "end": "2026-11-01"}).json()
    by_title = {s["title"]: s for s in calendar["sessions"]}
    assert by_title["Long run"]["match"]["activity_id"] == 12
    client.patch(f"/api/sessions/{by_title['Long run']['id']}", json={"skipped": True})
    calendar = client.get("/api/plan", params={"start": "2026-10-26", "end": "2026-11-01"}).json()
    assert {s["title"]: s for s in calendar["sessions"]}["Long run"]["match"] is None


def run_with_heart_rate(
    session: Session, activity_id: int, seconds_by_bpm: dict[int, float]
) -> None:
    session.add_all(
        ActivityHeartRate(activity_id=activity_id, bpm=bpm, seconds=seconds)
        for bpm, seconds in seconds_by_bpm.items()
    )
    session.add(
        ThresholdTest(
            day=date(2026, 10, 1), lt1_hr=144, lt2_hr=165, method="manual", created_at=NOW
        )
    )


def test_easy_run_above_lt1_scores_low(plan: sessionmaker[Session]) -> None:
    with plan() as session:
        row = session.get_one(PlannedSession, 1)
        row.intensity = "Z2"
        run_with_heart_rate(session, 11, {135: 900.0, 155: 900.0})
        match_sessions(session, date(2026, 10, 26), date(2026, 11, 1))
        match = session.get_one(SessionMatch, 1)

    assert json.loads(match.details)["hard_min"] == [0, 15]
    assert match.compliance == 50


def test_intervals_count_planned_minutes_above_lt1(plan: sessionmaker[Session]) -> None:
    with plan() as session:
        row = session.get_one(PlannedSession, 1)
        row.steps = [
            {"kind": "warmup", "duration_min": 10},
            {"kind": "intervals", "duration_min": 3, "repeats": 5, "target": "Z4"},
            {"kind": "cooldown", "duration_min": 5, "target": "Z1-Z2"},
        ]
        run_with_heart_rate(session, 11, {135: 900.0, 170: 900.0})
        match_sessions(session, date(2026, 10, 26), date(2026, 11, 1))
        match = session.get_one(SessionMatch, 1)

    assert json.loads(match.details)["hard_min"] == [15, 15]
    assert match.compliance == 100


def test_targets_without_a_zone_leave_intensity_out() -> None:
    assert target_zone("6x3 min Z4") == 4
    assert target_zone("zone 1 to 2") == 2
    assert target_zone("easy") is None
    by_feel = PlannedSession(steps=[{"kind": "steady", "duration_min": 40, "target": "easy"}])
    assert planned_hard_minutes(by_feel) is None
    by_distance = PlannedSession(steps=[{"kind": "intervals", "distance_km": 1, "target": "Z4"}])
    assert planned_hard_minutes(by_distance) is None


def season_weeks() -> list[dict[str, object]]:
    return [
        {"week_start": "2026-10-26", "phase": "base", "hours": 6, "climb_m": 800, "longest_h": 2},
        {"week_start": "2026-11-02", "phase": "build", "hours": 7, "focus": "First hill block"},
    ]


def test_season_outline_is_proposed_accepted_and_compared(plan: sessionmaker[Session]) -> None:
    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), plan, request_delay=0, sleep=lambda _: None)

    coach = Coach(plan, None, coach_settings(Settings.model_construct()))
    client = TestClient(single_app(plan, make_service, coach, schedule_sync=False))
    with plan() as session:
        context = ToolContext(session, NOW, 1.92)
        output, ok = run_tool(
            context,
            "propose_season",
            {"summary": "Outline", "reason": "Race in May", "season": {"weeks": season_weeks()}},
        )
        assert ok, output
        _, ok = run_tool(
            context,
            "propose_season",
            {
                "summary": "Outline",
                "reason": "Race in May",
                "season": {"weeks": [{"week_start": "2026-10-27", "phase": "base", "hours": 6}]},
            },
        )
        assert not ok
        session.commit()

    proposal = client.get("/api/proposals").json()[0]
    assert [week["phase"] for week in proposal["season"]["weeks"]] == ["base", "build"]
    assert client.post(f"/api/proposals/{proposal['id']}/accept").status_code == 200

    weeks = client.get("/api/season?start=2026-10-26&end=2026-11-08").json()
    assert weeks[0]["done_hours"] == pytest.approx(3000 / 3600 + 0.5 + 2 + 0.75)
    assert weeks[0]["done_longest_h"] == 2
    assert weeks[1]["focus"] == "First hill block"
    with plan() as session:
        output, _ = run_tool(
            ToolContext(session, NOW, 1.92),
            "get_season",
            {"start": "2026-10-26", "end": "2026-11-08"},
        )
        assert "week from 2026-10-26: base, targets 6 h, 800 m climbing on foot" in output
        assert "longest 2.0 h (week not over)" in output
        assert context_block(session, NOW).count("Season outline this week: base phase") == 1


def test_rating_is_saved_and_shown_to_the_coach(plan: sessionmaker[Session]) -> None:
    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), plan, request_delay=0, sleep=lambda _: None)

    coach = Coach(plan, None, coach_settings(Settings.model_construct()))
    client = TestClient(single_app(plan, make_service, coach, schedule_sync=False))

    assert client.get("/api/activities/12").json()["rating"] is None
    assert client.post("/api/activities/12/effort/8").json()["effort"] == 8
    assert client.post("/api/activities/12/effort/11").status_code == 422
    assert client.post("/api/activities/999/effort/5").status_code == 404
    saved = client.put(
        "/api/activities/12/rating", json={"effort": 7, "legs": 4, "pain": "left knee", "note": ""}
    )
    assert saved.json() == {"effort": 7, "legs": 4, "pain": "left knee", "note": None}
    assert client.get("/api/activities/12").json()["rating"]["legs"] == 4

    with plan() as session:
        context = ToolContext(session, NOW, 1.92)
        detail, _ = run_tool(context, "get_activity", {"activity_id": 12})
        listing, _ = run_tool(
            context, "list_activities", {"start": "2026-10-26", "end": "2026-10-30"}
        )
    assert "own rating: effort 7/10, legs 4/5 (sore), pain: left knee" in detail
    assert "felt 7/10" in listing


def test_fueling_is_saved_and_shown_to_the_coach(plan: sessionmaker[Session]) -> None:
    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), plan, request_delay=0, sleep=lambda _: None)

    coach = Coach(plan, None, coach_settings(Settings.model_construct()))
    client = TestClient(single_app(plan, make_service, coach, schedule_sync=False))

    assert client.get("/api/activities/12").json()["fuel"] is None
    assert client.put("/api/activities/999/fuel", json={}).status_code == 404
    saved = client.put(
        "/api/activities/12/fuel",
        json={"carbs_g": 120, "fluid_ml": 1000, "gut": "nausea after 2 h", "note": ""},
    )
    assert saved.json() == {
        "carbs_g": 120,
        "fluid_ml": 1000,
        "gut": "nausea after 2 h",
        "note": None,
    }
    with plan() as session:
        activity = session.get(Activity, 12)
        assert activity is not None and activity.duration_s
        hours = activity.duration_s / 3600
        context = ToolContext(session, NOW, 1.92)
        detail, _ = run_tool(context, "get_activity", {"activity_id": 12})
        listing, _ = run_tool(context, "get_fueling", {"start": "2026-10-01", "end": "2026-10-30"})
    expected = f"120 g carbohydrate ({120 / hours:.0f} per hour), 1000 ml fluid"
    assert f"Fueling logged by the athlete: {expected}" in detail
    assert "stomach: nausea after 2 h" in listing


def test_unavailable_days_reach_the_coach(plan: sessionmaker[Session]) -> None:
    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), plan, request_delay=0, sleep=lambda _: None)

    coach = Coach(plan, None, coach_settings(Settings.model_construct()))
    client = TestClient(single_app(plan, make_service, coach, schedule_sync=False))
    today = NOW.date()
    trip = {
        "first_day": str(today + timedelta(days=2)),
        "last_day": str(today + timedelta(days=4)),
        "reason": "travel",
        "note": "hotel gym only",
    }
    backwards = {**trip, "last_day": str(today)}
    assert client.post("/api/unavailable", json=backwards).status_code == 422
    period_id = client.post("/api/unavailable", json=trip).json()["id"]
    window = {"start": str(today), "end": str(today + timedelta(days=7))}
    assert [p["id"] for p in client.get("/api/unavailable", params=window).json()] == [period_id]

    with plan() as session:
        context = ToolContext(session, NOW, 1.92)
        text, _ = run_tool(context, "get_plan", window)
        expected = f"Cannot train as normal: {trip['first_day']} to {trip['last_day']} travel"
        assert f"{expected} (hotel gym only)" in text
        assert expected in context_block(session, NOW)
        saved, ok = run_tool(
            context,
            "set_unavailable",
            {"first_day": str(today), "last_day": str(today), "reason": "illness"},
        )
        assert ok
        assert saved.startswith(f"Saved: {today} illness")
        session.commit()

    assert client.delete(f"/api/unavailable/{period_id}").status_code == 204
    assert [p["reason"] for p in client.get("/api/unavailable", params=window).json()] == [
        "illness"
    ]
