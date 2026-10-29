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


def long_days(activities: list[Activity]) -> set[date]:
    seconds_by_day: dict[date, float] = defaultdict(float)
    for activity in activities:
        seconds_by_day[activity.local_date] += activity.duration_s or 0
    return {day for day, seconds in seconds_by_day.items() if seconds >= LONG_DAY_S}


def run_weeks(session: Session, first_week: date, last_week: date) -> list[RunWeek]:
    groups = sport_groups(session)
    activities = [
        a
        for a in session.scalars(
            select(Activity).where(
                Activity.local_date >= first_week,
                Activity.local_date < last_week + timedelta(days=7),
            )
        )
        if groups.get(a.type_key) in TIME_ON_FEET_GROUPS
    ]
    weeks: dict[date, RunWeek] = {}
    day = first_week
    while day <= last_week:
        weeks[day] = RunWeek(day)
        day += timedelta(weeks=1)

    for activity in activities:
        if groups.get(activity.type_key) != "run":
            continue
        week = weeks[week_start(activity.local_date)]
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
    return list(weeks.values())
