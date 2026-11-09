import re
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from itertools import count
from typing import Any

from garminconnect.exercises import EXERCISES
from garminconnect.workout import (
    WEIGHT_UNIT_KILOGRAM,
    BaseWorkout,
    ConditionType,
    CyclingWorkout,
    ExecutableStep,
    RepeatGroup,
    RunningWorkout,
    StepType,
    StrengthWorkout,
    TargetType,
    WorkoutSegment,
    create_repeat_group,
)

from garmin_coach.coach.plan import Exercise, Step
from garmin_coach.garmin.source import GarminNotFound, GarminSource
from garmin_coach.metrics.zones import Zone
from garmin_coach.models import PlannedSession

RUNNING_SPORTS = ("run", "vertical")
STRENGTH_WARMUP_MIN = 10
UNKNOWN_CATEGORY = "TOTAL_BODY"
NOTE_LENGTH = 250
DESCRIPTION_LENGTH = 1000
LOWEST_BPM = 40
HIGHEST_BPM = 220

STEP_TYPES = {
    "warmup": StepType.WARMUP,
    "cooldown": StepType.COOLDOWN,
    "interval": StepType.INTERVAL,
    "recovery": StepType.RECOVERY,
    "rest": StepType.REST,
}
CONDITIONS = {
    "lap.button": ConditionType.LAP_BUTTON,
    "time": ConditionType.TIME,
    "distance": ConditionType.DISTANCE,
    "reps": ConditionType.REPS,
}
NO_TARGET = {
    "workoutTargetTypeId": TargetType.NO_TARGET,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}
HEART_RATE = {
    "workoutTargetTypeId": TargetType.HEART_RATE_ZONE,
    "workoutTargetTypeKey": "heart.rate.zone",
    "displayOrder": 1,
}
RUN_STEP_TYPES = {"warmup": "warmup", "steady": "interval", "cooldown": "cooldown"}

ZONES = re.compile(r"\bZ([1-5])(?:\s*-\s*Z?([1-5]))?\b", re.IGNORECASE)
BPM_RANGE = re.compile(r"(\d{2,3})\s*-\s*(\d{2,3})\s*bpm", re.IGNORECASE)
TIME = re.compile(r"(\d+(?:[.,]\d+)?)\s*(min|s|sec)\b", re.IGNORECASE)
PER = r"(?:(?:/|per\b|each\b)\s*(.+))?"
REPS = re.compile(r"(\d+)(?:\s*-\s*(\d+))?\s*(?:reps?)?\s*" + PER, re.IGNORECASE)
TIMED_REPS = re.compile(r"(\d+)\s*(s|sec|min)\b\s*" + PER, re.IGNORECASE)
KILOGRAMS = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.IGNORECASE)
BODYWEIGHT = re.compile(r"body\s*weight|bw", re.IGNORECASE)


WorkoutStep = ExecutableStep | RepeatGroup


class WorkoutError(ValueError):
    pass


@dataclass(frozen=True)
class End:
    key: str
    value: float | None = None


LAP_BUTTON = End("lap.button")


def name_key(name: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    return " ".join(word.rstrip("s") for word in words)


CATALOG = {name_key(entry["name"]): entry for entry in EXERCISES}


def garmin_exercise(name: str) -> dict[str, str] | None:
    return CATALOG.get(name_key(name))


def find_exercises(term: str) -> list[str]:
    words = name_key(term).split()
    return [
        entry["name"] for entry in EXERCISES if all(w in name_key(entry["name"]) for w in words)
    ]


def note(*parts: str | None) -> str | None:
    text = ". ".join(part for part in parts if part)
    return text[:NOTE_LENGTH] or None


def executable(
    order: Iterator[int],
    kind: str,
    end: End,
    description: str | None = None,
    target: dict[str, Any] | None = None,
    **extra: Any,
) -> ExecutableStep:
    return ExecutableStep(
        stepOrder=next(order),
        stepType={
            "stepTypeId": STEP_TYPES[kind],
            "stepTypeKey": kind,
            "displayOrder": STEP_TYPES[kind],
        },
        endCondition={
            "conditionTypeId": CONDITIONS[end.key],
            "conditionTypeKey": end.key,
            "displayOrder": CONDITIONS[end.key],
            "displayable": True,
        },
        endConditionValue=end.value,
        description=description,
        **({"targetType": NO_TARGET} | (target or {}) | extra),
    )


def amount_end(duration_min: float | None, distance_km: float | None) -> End:
    if duration_min:
        return End("time", duration_min * 60)
    if distance_km:
        return End("distance", distance_km * 1000)
    return LAP_BUTTON


def seconds(match: re.Match[str]) -> float:
    value = float(match.group(1).replace(",", "."))
    return value * 60 if match.group(2).lower() == "min" else value


def recovery_end(recovery: str) -> End:
    match = TIME.search(recovery)
    return End("time", seconds(match)) if match else LAP_BUTTON


def heart_rate_target(text: str | None, zones: list[Zone] | None) -> dict[str, Any]:
    if not text:
        return {}
    bpm = BPM_RANGE.search(text)
    if bpm:
        return {
            "targetType": HEART_RATE,
            "targetValueOne": int(bpm.group(1)),
            "targetValueTwo": int(bpm.group(2)),
        }
    match = ZONES.search(text)
    if match is None:
        return {}
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if zones is None:
        return {"targetType": HEART_RATE, "zoneNumber": first} if first == last else {}
    return {
        "targetType": HEART_RATE,
        "targetValueOne": zones[first - 1].low or LOWEST_BPM,
        "targetValueTwo": zones[last - 1].high or HIGHEST_BPM,
    }


def run_step(step: Step, zones: list[Zone] | None, order: Iterator[int]) -> WorkoutStep:
    target = heart_rate_target(step.target, zones)
    end = amount_end(step.duration_min, step.distance_km)
    gradient = f"{step.grade_pct:g}% gradient" if step.grade_pct else None
    if step.kind != "intervals":
        return executable(order, RUN_STEP_TYPES[step.kind], end, note(gradient, step.note), target)
    group_order = next(order)
    repeat: list[WorkoutStep] = [
        executable(order, "interval", end, note(gradient, step.note), target)
    ]
    if step.recovery:
        repeat.append(
            executable(order, "recovery", recovery_end(step.recovery), note(step.recovery))
        )
    return create_repeat_group(step.repeats or 1, repeat, group_order)


def endurance_steps(
    row: PlannedSession, zones: list[Zone] | None, order: Iterator[int]
) -> list[WorkoutStep]:
    steps = [Step.model_validate(step) for step in row.steps or []]
    if steps:
        return [run_step(step, zones, order) for step in steps]
    end = amount_end(row.duration_min, row.distance_km)
    return [
        executable(
            order, "interval", end, note(row.intensity), heart_rate_target(row.intensity, zones)
        )
    ]


def reps_end(reps: str) -> tuple[End, str | None]:
    timed = TIMED_REPS.fullmatch(reps.strip())
    if timed:
        side = timed.group(3)
        return End("time", seconds(timed)), f"per {side}" if side else None
    counted = REPS.fullmatch(reps.strip())
    if counted is None:
        return LAP_BUTTON, reps
    low, high, side = counted.groups()
    parts = [f"{low}-{high} reps" if high else None, f"per {side}" if side else None]
    return End("reps", float(high or low)), ", ".join(part for part in parts if part) or None


def weight_kg(load: str | None) -> tuple[float | None, str | None]:
    if not load or BODYWEIGHT.fullmatch(load.strip()):
        return None, None
    kilograms = KILOGRAMS.fullmatch(load.strip())
    if kilograms:
        return float(kilograms.group(1).replace(",", ".")), None
    return None, load


def weight_fields(weight: float | None) -> dict[str, Any]:
    if weight is None:
        return {}
    return {"weightValue": weight * 1000, "weightUnit": dict(WEIGHT_UNIT_KILOGRAM)}


def exercise_steps(exercise: Exercise, order: Iterator[int]) -> list[WorkoutStep]:
    match = garmin_exercise(exercise.name)
    movement: dict[str, Any] = {
        "category": match["category"] if match else UNKNOWN_CATEGORY,
        "exerciseName": match["exercise"] if match else "",
    }
    name = None if match else exercise.name
    steps: list[WorkoutStep] = []
    for warmup in exercise.warmup_sets:
        description = note(name, "Warm-up set")
        steps.append(
            executable(
                order,
                "interval",
                End("reps", warmup.reps),
                description,
                **movement,
                **weight_fields(warmup.weight_kg or None),
            )
        )
        steps.append(executable(order, "rest", LAP_BUTTON))
    group_order = next(order)
    end, reps_note = reps_end(exercise.reps)
    weight, load_note = weight_kg(exercise.load)
    description = note(name, reps_note, load_note, exercise.note)
    work = executable(order, "interval", end, description, **movement, **weight_fields(weight))
    rest = executable(
        order, "rest", End("time", exercise.rest_s) if exercise.rest_s else LAP_BUTTON
    )
    steps.append(create_repeat_group(exercise.sets, [work, rest], group_order))
    return steps


def strength_steps(row: PlannedSession, order: Iterator[int]) -> list[WorkoutStep]:
    steps: list[WorkoutStep] = []
    if row.kind != "mobility":
        steps.append(executable(order, "warmup", End("time", STRENGTH_WARMUP_MIN * 60)))
    for exercise in row.exercises:
        steps += exercise_steps(Exercise.model_validate(exercise), order)
    return steps


def workout_payload(row: PlannedSession, zones: list[Zone] | None) -> dict[str, Any]:
    order = count(1)
    workout_type: type[BaseWorkout]
    steps: list[WorkoutStep]
    if row.exercises:
        workout_type = StrengthWorkout
        steps = strength_steps(row, order)
    elif row.sport in RUNNING_SPORTS or row.sport == "cycling":
        workout_type = CyclingWorkout if row.sport == "cycling" else RunningWorkout
        steps = endurance_steps(row, zones, order)
    else:
        raise WorkoutError(f"Garmin has no workouts for {row.sport} sessions without exercises")
    description = (row.description or "")[:DESCRIPTION_LENGTH] or None
    workout = workout_type(
        workoutName=row.title,
        estimatedDurationInSecs=round((row.duration_min or 0) * 60),
        workoutSegments=[],
        description=description,
    )
    workout.workoutSegments.append(
        WorkoutSegment(segmentOrder=1, sportType=workout.sportType, workoutSteps=steps)
    )
    return workout.to_dict()


def forget_workout(source: GarminSource, workout_id: int, schedule_id: int | None) -> None:
    if schedule_id is not None:
        with suppress(GarminNotFound):
            source.unschedule_workout(schedule_id)
    with suppress(GarminNotFound):
        source.delete_workout(workout_id)


def remove_from_watch(source: GarminSource, row: PlannedSession) -> None:
    if row.garmin_workout_id is None:
        return
    forget_workout(source, row.garmin_workout_id, row.garmin_schedule_id)
    row.garmin_workout_id = None
    row.garmin_schedule_id = None
    row.sent_to_watch_at = None


def send_to_watch(
    source: GarminSource, row: PlannedSession, zones: list[Zone] | None, now: datetime
) -> None:
    payload = workout_payload(row, zones)
    remove_from_watch(source, row)
    row.garmin_workout_id = source.upload_workout(payload)
    row.garmin_schedule_id = source.schedule_workout(row.garmin_workout_id, row.day)
    row.sent_to_watch_at = now
