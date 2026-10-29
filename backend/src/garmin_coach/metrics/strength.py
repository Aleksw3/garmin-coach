from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity, StrengthSet, StrengthSetOverride

PRIMARY_SET_SHARE = 1.0
SECONDARY_SET_SHARE = 0.5
EPLEY_MAX_REPS = 12

MUSCLES_BY_CATEGORY: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "SQUAT": (("quads", "glutes"), ("hamstrings",)),
    "LUNGE": (("quads", "glutes"), ("hamstrings",)),
    "DEADLIFT": (("hamstrings", "glutes"), ("lower_back",)),
    "HIP_RAISE": (("glutes",), ("hamstrings",)),
    "HIP_SWING": (("glutes", "hamstrings"), ("lower_back",)),
    "HIP_STABILITY": (("glutes",), ()),
    "LEG_CURL": (("hamstrings",), ()),
    "CALF_RAISE": (("calves",), ()),
    "HYPEREXTENSION": (("lower_back",), ("glutes", "hamstrings")),
    "OLYMPIC_LIFT": (("quads", "glutes", "hamstrings"), ("upper_back",)),
    "PLYO": (("quads", "calves"), ("glutes",)),
    "BENCH_PRESS": (("chest",), ("triceps", "shoulders")),
    "PUSH_UP": (("chest",), ("triceps", "shoulders")),
    "FLYE": (("chest",), ("shoulders",)),
    "SHOULDER_PRESS": (("shoulders",), ("triceps",)),
    "LATERAL_RAISE": (("shoulders",), ()),
    "SHOULDER_STABILITY": (("shoulders",), ()),
    "PULL_UP": (("upper_back",), ("biceps",)),
    "ROW": (("upper_back",), ("biceps",)),
    "SHRUG": (("upper_back",), ()),
    "CURL": (("biceps",), ()),
    "TRICEPS_EXTENSION": (("triceps",), ()),
    "CORE": (("core",), ()),
    "PLANK": (("core",), ()),
    "CRUNCH": (("core",), ()),
    "SIT_UP": (("core",), ()),
    "LEG_RAISE": (("core",), ()),
    "CHOP": (("core",), ()),
    "CARRY": (("core",), ("upper_back",)),
}

SINGLE_LEG_OR_ECCENTRIC_MARKERS = (
    "SINGLE_LEG",
    "SPLIT_SQUAT",
    "STEP_UP",
    "STEP_DOWN",
    "PISTOL",
    "NORDIC",
    "ECCENTRIC",
    "LUNGE",
)


@dataclass
class EffectiveSet:
    day: date
    activity_id: int
    set_index: int
    category: str | None
    name: str | None
    reps: int | None
    weight_kg: float | None


def effective_sets(session: Session, first: date, last: date) -> list[EffectiveSet]:
    rows = session.execute(
        select(StrengthSet, Activity.local_date)
        .join(Activity, Activity.id == StrengthSet.activity_id)
        .where(
            Activity.local_date >= first,
            Activity.local_date <= last,
            StrengthSet.set_type == "ACTIVE",
        )
        .order_by(Activity.local_date, StrengthSet.activity_id, StrengthSet.set_index)
    )
    overrides = {
        (o.activity_id, o.set_index): o for o in session.scalars(select(StrengthSetOverride))
    }
    sets = []
    for strength_set, day in rows:
        override = overrides.get((strength_set.activity_id, strength_set.set_index))
        if override is not None and override.deleted:
            continue
        source = override or strength_set
        sets.append(
            EffectiveSet(
                day=day,
                activity_id=strength_set.activity_id,
                set_index=strength_set.set_index,
                category=source.exercise_category,
                name=source.exercise_name,
                reps=source.reps,
                weight_kg=source.weight_kg,
            )
        )
    return sets


def is_hard_set(strength_set: EffectiveSet) -> bool:
    return bool(strength_set.reps) and strength_set.category in MUSCLES_BY_CATEGORY


def sets_per_muscle(sets: list[EffectiveSet]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for strength_set in filter(is_hard_set, sets):
        primary, secondary = MUSCLES_BY_CATEGORY[strength_set.category or ""]
        for muscle in primary:
            totals[muscle] += PRIMARY_SET_SHARE
        for muscle in secondary:
            totals[muscle] += SECONDARY_SET_SHARE
    return dict(totals)


def is_single_leg_or_eccentric(strength_set: EffectiveSet) -> bool:
    text = f"{strength_set.category or ''} {strength_set.name or ''}"
    return any(marker in text for marker in SINGLE_LEG_OR_ECCENTRIC_MARKERS)


def epley_one_rep_max(weight_kg: float | None, reps: int | None) -> float | None:
    if not weight_kg or not reps or reps > EPLEY_MAX_REPS:
        return None
    return weight_kg if reps == 1 else weight_kg * (1 + reps / 30)


def best_one_rep_max(sets: list[EffectiveSet]) -> dict[str, tuple[date, float]]:
    best: dict[str, tuple[date, float]] = {}
    for strength_set in sets:
        estimate = epley_one_rep_max(strength_set.weight_kg, strength_set.reps)
        exercise = strength_set.name or strength_set.category
        if estimate is None or exercise is None:
            continue
        if exercise not in best or estimate > best[exercise][1]:
            best[exercise] = (strength_set.day, estimate)
    return best


def weekly_sets_per_muscle(
    session: Session, first_week: date, last_week: date
) -> dict[date, dict[str, float]]:
    sets = effective_sets(session, first_week, last_week + timedelta(days=6))
    by_week: dict[date, list[EffectiveSet]] = defaultdict(list)
    for strength_set in sets:
        by_week[strength_set.day - timedelta(days=strength_set.day.weekday())].append(strength_set)
    return {week: sets_per_muscle(week_sets) for week, week_sets in sorted(by_week.items())}
