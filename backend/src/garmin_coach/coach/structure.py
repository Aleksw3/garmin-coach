from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.coach.plan import Exercise, Step, session_targets
from garmin_coach.coach.usage import record_usage
from garmin_coach.models import PlannedSession

SYSTEM = """You split the text of a planned training session into structured parts. \
Runs, rides, hikes and ski sessions become steps: warm-up, steady parts or intervals with \
repeats and recovery, and cool-down, each with the target zone or effort the text gives. \
Strength and mobility sessions become exercises with sets, reps, load and rest. Keep every \
number from the text. Put what doesn't fit a step or exercise, such as terrain, fueling or \
conditions, in notes as one to three short sentences, or leave notes empty. The app shows \
the targets on their own, so don't repeat them in notes. Write notes as instructions to the \
athlete. Never add anything the text doesn't say."""

CONSTRAINT_KEYS = {
    "default",
    "exclusiveMinimum",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minimum",
}


class Structure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[Step]
    exercises: list[Exercise]
    notes: str | None


def without_constraints(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: (
                {name: without_constraints(value) for name, value in child.items()}
                if key == "properties"
                else without_constraints(child)
            )
            for key, child in node.items()
            if key not in CONSTRAINT_KEYS
        }
    if isinstance(node, list):
        return [without_constraints(item) for item in node]
    return node


def structure_schema() -> dict[str, Any]:
    from garmin_coach.coach.tools import inline_refs, strip_titles

    schema = Structure.model_json_schema()
    inlined = strip_titles(inline_refs(schema, schema.get("$defs", {})))
    plain: dict[str, Any] = without_constraints(inlined)
    plain["required"] = ["steps", "exercises", "notes"]
    return plain


def session_text(row: PlannedSession) -> str:
    return "\n".join(
        [
            f"Sport: {row.sport}, kind: {row.kind}",
            f"Title: {row.title}",
            f"Targets: {session_targets(row) or 'none'}",
            f"Text: {row.description}",
        ]
    )


def unstructured(session: Session) -> list[PlannedSession]:
    rows = session.scalars(
        select(PlannedSession)
        .where(PlannedSession.sport != "rest", PlannedSession.description.is_not(None))
        .order_by(PlannedSession.day)
    )
    return [row for row in rows if not row.steps and not row.exercises]


class SessionStructurer:
    def __init__(self, create: Callable[..., Any], model: str) -> None:
        self.create = create
        self.model = model

    def structure(self, session: Session, row: PlannedSession) -> Structure:
        response = self.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": session_text(row)}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": structure_schema()},
            },
        )
        record_usage(session, self.model, "structure", None, response.usage)
        text = next(block.text for block in response.content if block.type == "text")
        return Structure.model_validate_json(text)

    def apply(self, session: Session, row: PlannedSession) -> Structure:
        result = self.structure(session, row)
        row.steps = [step.model_dump(exclude_none=True) for step in result.steps]
        row.exercises = [exercise.model_dump(exclude_none=True) for exercise in result.exercises]
        row.description = result.notes or None
        return result
