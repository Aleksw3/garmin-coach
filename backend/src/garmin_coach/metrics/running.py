from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity
from garmin_coach.normalize.sports import sport_groups
from garmin_coach.reports import week_start

FLAT_MAX_CLIMB_PER_KM = 10.0
ROLLING_MAX_CLIMB_PER_KM = 25.0
LONG_DAY_S = 90 * 60
TIME_ON_FEET_GROUPS = ("run", "vertical")
DESCENT_BASELINE_WEEKS = 4
DESCENT_JUMP_RATIO = 1.5
DESCENT_JUMP_MIN_M = 1000.0


def climb_per_km(elevation_gain_m: float | None, distance_m: float | None) -> float | None:
    if elevation_gain_m is None or not distance_m:
        return None
    return elevation_gain_m / (distance_m / 1000)


def terrain(climb: float | None) -> str:
    if climb is None:
        return "unknown"
    if climb < FLAT_MAX_CLIMB_PER_KM:
        return "flat"
    if climb < ROLLING_MAX_CLIMB_PER_KM:
        return "rolling"
    return "mountain"


@dataclass
class RunWeek:
    week_start: date
    runs: int = 0
    distance_km: float = 0.0
    hours: float = 0.0
    elevation_gain_m: float = 0.0
    elevation_loss_m: float = 0.0
    longest_run_h: float = 0.0
    biggest_climb_m: float = 0.0
    hours_by_terrain: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    back_to_back_long_days: int = 0
    descent_on_foot_m: float = 0.0
    biggest_descent_m: float = 0.0
    descent_baseline_m: float | None = None

    @property
    def descent_ratio(self) -> float | None:
        if not self.descent_baseline_m:
            return None
        return self.descent_on_foot_m / self.descent_baseline_m

    @property
    def descent_jump(self) -> bool:
        ratio = self.descent_ratio
        return (
            ratio is not None
            and ratio >= DESCENT_JUMP_RATIO
            and self.descent_on_foot_m >= DESCENT_JUMP_MIN_M
        )


def long_days(activities: list[Activity]) -> set[date]:
    seconds_by_day: dict[date, float] = defaultdict(float)
    for activity in activities:
        seconds_by_day[activity.local_date] += activity.duration_s or 0
    return {day for day, seconds in seconds_by_day.items() if seconds >= LONG_DAY_S}


def run_weeks(session: Session, first_week: date, last_week: date) -> list[RunWeek]:
    groups = sport_groups(session)
    baseline_from = first_week - timedelta(weeks=DESCENT_BASELINE_WEEKS)
    activities = [
        a
        for a in session.scalars(
            select(Activity).where(
                Activity.local_date >= baseline_from,
                Activity.local_date < last_week + timedelta(days=7),
            )
        )
        if groups.get(a.type_key) in TIME_ON_FEET_GROUPS
    ]
    weeks: dict[date, RunWeek] = {}
    day = baseline_from
    while day <= last_week:
        weeks[day] = RunWeek(day)
        day += timedelta(weeks=1)

    for activity in activities:
        week = weeks[week_start(activity.local_date)]
        loss = activity.elevation_loss_m or 0
        week.descent_on_foot_m += loss
        week.biggest_descent_m = max(week.biggest_descent_m, loss)
        if groups.get(activity.type_key) != "run":
            continue
        hours = (activity.duration_s or 0) / 3600
        week.runs += 1
        week.distance_km += (activity.distance_m or 0) / 1000
        week.hours += hours
        week.elevation_gain_m += activity.elevation_gain_m or 0
        week.elevation_loss_m += activity.elevation_loss_m or 0
        week.longest_run_h = max(week.longest_run_h, hours)
        week.biggest_climb_m = max(week.biggest_climb_m, activity.elevation_gain_m or 0)
        week.hours_by_terrain[
            terrain(climb_per_km(activity.elevation_gain_m, activity.distance_m))
        ] += hours

    long = long_days(activities)
    for day in long:
        if day - timedelta(days=1) in long:
            weeks[week_start(day)].back_to_back_long_days += 1
    ordered = list(weeks.values())
    for index in range(DESCENT_BASELINE_WEEKS, len(ordered)):
        before = ordered[index - DESCENT_BASELINE_WEEKS : index]
        ordered[index].descent_baseline_m = sum(w.descent_on_foot_m for w in before) / len(before)
    return ordered[DESCENT_BASELINE_WEEKS:]
