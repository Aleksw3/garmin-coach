from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity, ActivityHeartRate, ThresholdTest
from garmin_coach.reports import week_start

ZONE_NAMES = ("Recovery", "Aerobic base", "Tempo", "Threshold", "Max")
ZONE_TWO_SHARE_OF_LT1 = 0.9
ZONE_FOUR_ABOVE_LT2 = 1.05
RETEST_AFTER_DAYS = 56


@dataclass(frozen=True)
class Zone:
    number: int
    name: str
    low: int | None
    high: int | None


def hr_zones(lt1: int, lt2: int) -> list[Zone]:
    lows: list[int | None] = [
        None,
        round(lt1 * ZONE_TWO_SHARE_OF_LT1),
        lt1 + 1,
        lt2 + 1,
        round(lt2 * ZONE_FOUR_ABOVE_LT2) + 1,
    ]
    highs: list[int | None] = [low - 1 for low in lows[1:] if low is not None]
    highs.append(None)
    return [
        Zone(number, name, low, high)
        for number, (name, low, high) in enumerate(zip(ZONE_NAMES, lows, highs, strict=True), 1)
    ]


def zone_of(bpm: float, zones: list[Zone]) -> int:
    for zone in reversed(zones):
        if zone.low is not None and bpm >= zone.low:
            return zone.number
    return 1


def zone_range(zone: Zone) -> str:
    if zone.low is None:
        return f"under {zone.high + 1 if zone.high else '?'}"
    if zone.high is None:
        return f"{zone.low} and up"
    return f"{zone.low}-{zone.high}"


def latest_test(session: Session) -> ThresholdTest | None:
    return session.scalars(
        select(ThresholdTest).order_by(ThresholdTest.day.desc(), ThresholdTest.id.desc()).limit(1)
    ).first()


def current_zones(session: Session) -> list[Zone] | None:
    test = latest_test(session)
    return None if test is None else hr_zones(test.lt1_hr, test.lt2_hr)


def retest_due(test: ThresholdTest, today: date) -> bool:
    return (today - test.day).days > RETEST_AFTER_DAYS


def zones_line(session: Session, today: date | None = None) -> str | None:
    test = latest_test(session)
    if test is None:
        return None
    stale = (
        f". That test is {(today - test.day).days} days old, more than "
        f"{RETEST_AFTER_DAYS // 7} weeks, so a new LT1 and LT2 test is due"
        if today is not None and retest_due(test, today)
        else ""
    )
    ranges = ", ".join(
        f"Z{zone.number} {zone_range(zone)}" for zone in hr_zones(test.lt1_hr, test.lt2_hr)
    )
    return (
        f"HR zones from LT1 {test.lt1_hr} and LT2 {test.lt2_hr} ({test.day}): {ranges} bpm{stale}"
    )


def activity_zone_seconds(session: Session, activity_id: int, zones: list[Zone]) -> list[float]:
    seconds = [0.0] * len(zones)
    rows = session.execute(
        select(ActivityHeartRate.bpm, ActivityHeartRate.seconds).where(
            ActivityHeartRate.activity_id == activity_id
        )
    )
    for bpm, total in rows:
        seconds[zone_of(bpm, zones) - 1] += total
    return seconds


def weekly_zone_seconds(
    session: Session, first: date, last: date, activity_ids: list[int], zones: list[Zone]
) -> dict[date, list[float]]:
    weeks: dict[date, list[float]] = defaultdict(lambda: [0.0] * len(zones))
    rows = session.execute(
        select(Activity.local_date, ActivityHeartRate.bpm, func.sum(ActivityHeartRate.seconds))
        .join(Activity, Activity.id == ActivityHeartRate.activity_id)
        .where(
            Activity.local_date >= first,
            Activity.local_date <= last,
            Activity.id.in_(activity_ids),
        )
        .group_by(Activity.local_date, ActivityHeartRate.bpm)
    )
    for day, bpm, total in rows:
        weeks[week_start(day)][zone_of(bpm, zones) - 1] += total
    return dict(weeks)
