import json
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.coach.plan import SessionSpec, session_row, session_structure
from garmin_coach.coach.structure import SessionStructurer, structure_schema, unstructured
from garmin_coach.models import ApiUsage, Plan, PlannedSession

STRUCTURE = {
    "steps": [],
    "exercises": [
        {"name": "Back squat", "sets": 3, "reps": "8", "load": "60 kg", "rest_s": None},
        {"name": "Copenhagen plank", "sets": 2, "reps": "20 s/side", "note": None},
    ],
    "notes": "Keep it light.",
}


def fake_create(**params: Any) -> SimpleNamespace:
    assert "minLength" not in json.dumps(params["output_config"])
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(STRUCTURE))],
        usage=SimpleNamespace(
            input_tokens=500,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            output_tokens=100,
        ),
    )


def add_plan(session: Session) -> None:
    session.add(
        Plan(
            id=1,
            title="Block",
            start_date=date(2026, 11, 3),
            end_date=date(2026, 11, 4),
            created_at=datetime(2026, 11, 2),
        )
    )


def test_steps_and_exercises_round_trip(session: Session) -> None:
    add_plan(session)
    spec = SessionSpec.model_validate(
        {
            "day": "2026-11-04",
            "sport": "run",
            "kind": "hills",
            "title": "Hill repeats",
            "steps": [
                {"kind": "warmup", "duration_min": 15, "target": "Z1"},
                {
                    "kind": "intervals",
                    "repeats": 5,
                    "duration_min": 3,
                    "target": "Z3",
                    "recovery": "jog down",
                },
            ],
        }
    )
    session.add(session_row(1, spec))
    session.flush()
    row = session.scalars(select(PlannedSession)).one()

    assert row.exercises == []
    assert session_structure(row) == (
        "steps: warmup 15 min Z1; intervals 5x 3 min Z3 recovery jog down"
    )


def test_structurer_fills_old_sessions(session: Session) -> None:
    add_plan(session)
    session.add(
        PlannedSession(
            plan_id=1,
            day=date(2026, 11, 3),
            sport="strength",
            kind="strength",
            title="Strength A",
            description="Back squat 3x8 @ 60 kg. Copenhagen plank 2x20 s/side. Keep it light.",
        )
    )
    session.flush()
    (row,) = unstructured(session)

    SessionStructurer(fake_create, "claude-haiku-5-5").apply(session, row)

    assert row.steps == []
    assert row.exercises[0] == {"name": "Back squat", "sets": 3, "reps": "8", "load": "60 kg"}
    assert row.description == "Keep it light."
    assert session_structure(row) == (
        "exercises: Back squat 3x8 @ 60 kg; Copenhagen plank 2x20 s/side"
    )
    assert unstructured(session) == []
    assert session.scalar(select(ApiUsage.purpose)) == "structure"
    assert structure_schema()["required"] == ["steps", "exercises", "notes"]
