import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import DailyWellness

ROLLING_DAYS = 7
BASELINE_DAYS = 60
SMALLEST_WORTHWHILE_CHANGE_SD = 0.5
MIN_ROLLING_VALUES = 4
MIN_BASELINE_VALUES = 30


@dataclass
class BaselineStatus:
    day: date
    rolling: float
    baseline: float
    low: float
    high: float

    @property
    def status(self) -> str:
        if self.rolling < self.low:
            return "below"
        if self.rolling > self.high:
            return "above"
        return "within"


def window(values: dict[date, float], last: date, days: int) -> list[float]:
    return [
        values[last - timedelta(days=offset)]
        for offset in range(days)
        if last - timedelta(days=offset) in values
    ]


def baseline_status(values: dict[date, float], day: date) -> BaselineStatus | None:
    rolling = window(values, day, ROLLING_DAYS)
    baseline = window(values, day, BASELINE_DAYS)
    if len(rolling) < MIN_ROLLING_VALUES or len(baseline) < MIN_BASELINE_VALUES:
        return None
    mean = statistics.fmean(baseline)
    change = SMALLEST_WORTHWHILE_CHANGE_SD * statistics.stdev(baseline)
    return BaselineStatus(day, statistics.fmean(rolling), mean, mean - change, mean + change)


def hrv_baseline(session: Session, first: date, last: date) -> list[BaselineStatus]:
    rows = session.execute(
        select(DailyWellness.day, DailyWellness.hrv_last_night).where(
            DailyWellness.day > first - timedelta(days=BASELINE_DAYS),
            DailyWellness.day <= last,
            DailyWellness.hrv_last_night.is_not(None),
        )
    )
    ln_hrv = {day: math.log(value) for day, value in rows if value and value > 0}
    statuses = []
    day = first
    while day <= last:
        status = baseline_status(ln_hrv, day)
        if status is not None:
            statuses.append(status)
        day += timedelta(days=1)
    return statuses


def resting_hr_baseline(session: Session, day: date) -> BaselineStatus | None:
    rows = session.execute(
        select(DailyWellness.day, DailyWellness.resting_hr).where(
            DailyWellness.day > day - timedelta(days=BASELINE_DAYS),
            DailyWellness.day <= day,
            DailyWellness.resting_hr.is_not(None),
        )
    )
    return baseline_status({d: float(value) for d, value in rows if value is not None}, day)
