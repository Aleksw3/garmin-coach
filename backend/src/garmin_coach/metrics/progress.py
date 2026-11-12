import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.course import Course, describe
from garmin_coach.metrics.projection import ON_FOOT_GROUPS, clock, effort_km, project
from garmin_coach.metrics.running import climb_per_km, terrain
from garmin_coach.models import Activity, ActivityFuel, Climb, Goal, GoalCourse
from garmin_coach.normalize.sports import sport_groups
from garmin_coach.reports import week_start

HISTORY_WEEKS = 52
COMPARE_DAYS = 84
RECENT_DAYS = 42
FORM_DAYS = 90
LONG_RUN_S = 90 * 60
MIN_CLIMB_S = 600.0
MIN_CLIMB_GRADE = 0.08
MIN_CLIMBS = 4

CLOCK_TARGET = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
HOURS_TARGET = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:h\b|hours?|timer?)", re.IGNORECASE)


def target_seconds(target: str | None) -> float | None:
    if not target:
        return None
    if found := CLOCK_TARGET.search(target):
        hours, minutes, seconds = (int(part or 0) for part in found.groups())
        return hours * 3600 + minutes * 60 + seconds
    if found := HOURS_TARGET.search(target):
        return float(found.group(1).replace(",", ".")) * 3600
    return None


@dataclass(frozen=True)
class Estimate:
    day: date
    fast_s: float
    slow_s: float


@dataclass(frozen=True)
class ClimbEffort:
    day: date
    meters_per_hour: float


@dataclass(frozen=True)
class Training:
    on_foot: list[Activity]
    run_ids: set[int]
    climbs: list[ClimbEffort]
    carbs_g: dict[int, float]

    def within(self, day: date, days: int) -> list[Activity]:
        return [a for a in self.on_foot if day - timedelta(days=days) < a.local_date <= day]

    def long_runs(self, day: date) -> list[Activity]:
        return [
            a
            for a in self.within(day, FORM_DAYS)
            if a.id in self.run_ids and (a.duration_s or 0) >= LONG_RUN_S
        ]


def load_training(session: Session, first: date, last: date) -> Training:
    groups = sport_groups(session)
    activities = [
        a
        for a in session.scalars(
            select(Activity).where(Activity.local_date > first, Activity.local_date <= last)
        )
        if groups.get(a.type_key) in ON_FOOT_GROUPS
    ]
    ids = {a.id: a.local_date for a in activities}
    climbs = [
        ClimbEffort(ids[activity_id], gain / seconds * 3600)
        for activity_id, length, gain, seconds in session.execute(
            select(Climb.activity_id, Climb.length_m, Climb.gain_m, Climb.seconds).where(
                Climb.seconds >= MIN_CLIMB_S
            )
        )
        if activity_id in ids and gain / length >= MIN_CLIMB_GRADE
    ]
    carbs = {
        activity_id: grams
        for activity_id, grams in session.execute(
            select(ActivityFuel.activity_id, ActivityFuel.carbs_g)
        )
        if activity_id in ids and grams is not None
    }
    run_ids = {a.id for a in activities if groups.get(a.type_key) == "run"}
    return Training(activities, run_ids, climbs, carbs)


def activity_effort_km(activity: Activity) -> float:
    return effort_km((activity.distance_m or 0) / 1000, activity.elevation_gain_m or 0)


def weekly_effort_km(training: Training, day: date) -> float | None:
    recent = training.within(day, RECENT_DAYS)
    return sum(map(activity_effort_km, recent)) / (RECENT_DAYS / 7) if recent else None


def longest_effort_km(training: Training, day: date) -> float | None:
    return max(map(activity_effort_km, training.within(day, RECENT_DAYS)), default=None)


def biggest_descent_m(training: Training, day: date) -> float | None:
    return max((a.elevation_loss_m or 0 for a in training.within(day, RECENT_DAYS)), default=None)


def climb_rate(training: Training, day: date) -> float | None:
    rates = [
        c.meters_per_hour for c in training.climbs if day - timedelta(days=FORM_DAYS) < c.day <= day
    ]
    return statistics.quantiles(rates, n=4)[-1] if len(rates) >= MIN_CLIMBS else None


def decoupling(training: Training, day: date) -> float | None:
    drifts = [
        a.decoupling_pct
        for a in training.long_runs(day)
        if a.decoupling_pct is not None
        and terrain(climb_per_km(a.elevation_gain_m, a.distance_m)) == "flat"
    ]
    return statistics.median(drifts) if drifts else None


def carbs_per_hour(training: Training, day: date) -> float | None:
    rates = [
        training.carbs_g[a.id] / ((a.duration_s or 0) / 3600)
        for a in training.within(day, FORM_DAYS)
        if a.id in training.carbs_g and (a.duration_s or 0) >= LONG_RUN_S
    ]
    return statistics.median(rates) if rates else None


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    unit: str
    basis: str
    value: Callable[[Training, date], float | None]
    higher_is_better: bool = True


MEASURES = (
    Measure(
        "volume",
        "Volume on foot",
        "effort-km per week",
        "Mean of the last 6 weeks of runs and hikes, where 100 m of climbing counts as 1 km",
        weekly_effort_km,
    ),
    Measure(
        "longest",
        "Longest day",
        "effort-km",
        "Longest run or hike of the last 6 weeks",
        longest_effort_km,
    ),
    Measure(
        "descent",
        "Biggest descent",
        "m",
        "Most descent in one run or hike of the last 6 weeks",
        biggest_descent_m,
    ),
    Measure(
        "climb_rate",
        "Climb speed",
        "m per hour",
        "Upper quartile of the climbs of 10 minutes or more at 8% or steeper in the last "
        f"90 days, with at least {MIN_CLIMBS} climbs",
        climb_rate,
    ),
    Measure(
        "durability",
        "Heart rate drift",
        "%",
        "Median decoupling of heart rate from pace on flat runs of 90 minutes or more in the "
        "last 90 days, flat meaning under 10 m of climbing per km. Lower means the pace holds "
        "longer. Hilly runs are left out, because the terrain moves this number more than "
        "fatigue does",
        decoupling,
        higher_is_better=False,
    ),
    Measure(
        "fueling",
        "Carbohydrate",
        "g per hour",
        "Median of the logged fueling on runs and hikes of 90 minutes or more in the last 90 days",
        carbs_per_hour,
    ),
)


@dataclass(frozen=True)
class Part:
    key: str
    label: str
    unit: str
    basis: str
    higher_is_better: bool
    now: float | None
    before: float | None
    race: float | None


@dataclass(frozen=True)
class Progress:
    target_s: float | None
    race_day: date | None
    estimates: list[Estimate]
    parts: list[Part]

    @property
    def seconds_per_week_needed(self) -> float | None:
        if self.target_s is None or self.race_day is None or not self.estimates:
            return None
        latest = self.estimates[-1]
        weeks = (self.race_day - latest.day).days / 7
        return (latest.fast_s - self.target_s) / weeks if weeks > 0 else None


def estimates(session: Session, goal: Goal, today: date) -> list[Estimate]:
    days = [week_start(today) - timedelta(weeks=n) for n in range(HISTORY_WEEKS, 0, -1)]
    found = []
    for day in [*days, today]:
        projection = project(session, goal, day)
        if projection is not None:
            found.append(Estimate(day, projection.fast_s, projection.slow_s))
    return found


def race_demands(goal: Goal, course: Course | None) -> dict[str, float]:
    if course is not None:
        return {
            "longest": effort_km(course.distance_m / 1000, course.gain_m),
            "descent": course.loss_m,
        }
    if goal.distance_km:
        return {"longest": effort_km(goal.distance_km, goal.elevation_gain_m or 0)}
    return {}


def progress(session: Session, goal: Goal, today: date) -> Progress:
    row = session.get(GoalCourse, goal.id)
    demands = race_demands(goal, describe(row) if row else None)
    before = today - timedelta(days=COMPARE_DAYS)
    training = load_training(session, before - timedelta(days=FORM_DAYS), today)
    parts = [
        Part(
            m.key,
            m.label,
            m.unit,
            m.basis,
            m.higher_is_better,
            m.value(training, today),
            m.value(training, before),
            demands.get(m.key),
        )
        for m in MEASURES
    ]
    return Progress(
        target_seconds(goal.target), goal.target_date, estimates(session, goal, today), parts
    )


def amount(value: float | None, unit: str) -> str:
    return "no data" if value is None else f"{value:.0f} {unit}"


def progress_text(found: Progress) -> list[str]:
    lines = []
    if found.estimates:
        latest = found.estimates[-1]
        earlier = [e for e in found.estimates if e.day <= latest.day - timedelta(days=COMPARE_DAYS)]
        line = f"Finish estimate now {clock(latest.fast_s)} to {clock(latest.slow_s)}"
        if earlier:
            line += f", and {clock(earlier[-1].fast_s)} to {clock(earlier[-1].slow_s)} 12 weeks ago"
        lines.append(line + ".")
        if found.target_s is not None:
            lines.append(f"Target time {clock(found.target_s)}.")
        needed = found.seconds_per_week_needed
        if needed is not None and needed > 0:
            lines.append(
                f"The fast end has to drop by about {needed / 60:.1f} minutes per week to "
                f"reach the target on {found.race_day}."
            )
        lines.append(
            "The estimate comes from the 3 fastest long runs or hikes of the last 180 days. "
            "It moves when a fast run enters or leaves that window, and it reflects how hard "
            "those runs were. Do not read a change of a few minutes as a change in fitness."
        )
    else:
        lines.append("No finish estimate. It needs a run or hike of 60 minutes or more.")
    lines.append("Parts of the race, now and 12 weeks ago:")
    for part in found.parts:
        line = (
            f"- {part.label}: now {amount(part.now, part.unit)}, "
            f"12 weeks ago {amount(part.before, part.unit)}"
        )
        if part.race is not None:
            line += f", the race has {amount(part.race, part.unit)}"
        lines.append(f"{line}. {part.basis}.")
    lines.append(
        "No measure covers technique on rough ground. Ask the athlete how the descents felt."
    )
    return lines
