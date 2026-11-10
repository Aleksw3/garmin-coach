import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity, AthleteProfile, DailyWellness

ACUTE_DAYS = 7
CHRONIC_DAYS = 42
MAX_HR_LOOKBACK_DAYS = 365
DEFAULT_RESTING_HR = 60.0
MIN_ACTIVITIES_FOR_SCALE = 10


@dataclass
class DailyLoad:
    day: date
    load: float
    acute: float
    chronic: float


def banister_trimp(
    duration_s: float | None,
    avg_hr: float | None,
    resting_hr: float,
    max_hr: float,
    coefficient: float,
) -> float | None:
    if not duration_s or not avg_hr or max_hr <= resting_hr:
        return None
    heart_rate_reserve = min(max((avg_hr - resting_hr) / (max_hr - resting_hr), 0.0), 1.0)
    minutes = duration_s / 60
    return minutes * heart_rate_reserve * 0.64 * math.exp(coefficient * heart_rate_reserve)


def activity_load(
    activity: Activity,
    resting_hr: float,
    max_hr: float,
    trimp_coefficient: float,
    garmin_load_per_trimp: float = 1.0,
) -> float:
    if activity.training_load is not None:
        return activity.training_load
    trimp = banister_trimp(
        activity.duration_s, activity.avg_hr, resting_hr, max_hr, trimp_coefficient
    )
    return (trimp or 0.0) * garmin_load_per_trimp


def garmin_load_per_trimp(
    activities: list[Activity], resting_hr: float, max_hr: float, trimp_coefficient: float
) -> float:
    ratios = []
    for activity in activities:
        trimp = banister_trimp(
            activity.duration_s, activity.avg_hr, resting_hr, max_hr, trimp_coefficient
        )
        if activity.training_load and trimp:
            ratios.append(activity.training_load / trimp)
    return median(ratios) if len(ratios) >= MIN_ACTIVITIES_FOR_SCALE else 1.0


def exponential_average(previous: float, value: float, days: int) -> float:
    weight = 2 / (days + 1)
    return weight * value + (1 - weight) * previous


def load_series(loads_by_day: dict[date, float], first: date, last: date) -> list[DailyLoad]:
    acute = chronic = 0.0
    series = []
    day = first
    while day <= last:
        load = loads_by_day.get(day, 0.0)
        acute = exponential_average(acute, load, ACUTE_DAYS)
        chronic = exponential_average(chronic, load, CHRONIC_DAYS)
        series.append(DailyLoad(day, load, acute, chronic))
        day += timedelta(days=1)
    return series


def athlete_heart_rates(session: Session, as_of: date) -> tuple[float, float]:
    resting = session.scalar(
        select(func.avg(DailyWellness.resting_hr)).where(
            DailyWellness.day > as_of - timedelta(days=60), DailyWellness.day <= as_of
        )
    )
    profile = session.get(AthleteProfile, 1)
    maximum = (profile.max_hr if profile else None) or session.scalar(
        select(func.max(Activity.max_hr)).where(
            Activity.local_date > as_of - timedelta(days=MAX_HR_LOOKBACK_DAYS),
            Activity.local_date <= as_of,
        )
    )
    return float(resting or DEFAULT_RESTING_HR), float(maximum or 0.0)


def training_load(
    session: Session, first: date, last: date, trimp_coefficient: float
) -> list[DailyLoad]:
    earliest = session.scalar(select(func.min(Activity.local_date)))
    if earliest is None:
        return load_series({}, first, last)
    resting_hr, max_hr = athlete_heart_rates(session, last)
    activities = list(session.scalars(select(Activity).where(Activity.local_date <= last)))
    scale = garmin_load_per_trimp(activities, resting_hr, max_hr, trimp_coefficient)
    loads: dict[date, float] = defaultdict(float)
    for activity in activities:
        loads[activity.local_date] += activity_load(
            activity, resting_hr, max_hr, trimp_coefficient, scale
        )
    series = load_series(loads, min(earliest, first), last)
    return [entry for entry in series if entry.day >= first]


def trimp_for(session: Session, default: float) -> float:
    profile = session.get(AthleteProfile, 1)
    return profile.trimp_coefficient if profile and profile.trimp_coefficient else default
