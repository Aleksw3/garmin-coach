from datetime import date

from sqlalchemy.orm import Session

from garmin_coach import raw_store
from garmin_coach.normalize import rebuild_all
from garmin_coach.reports import week_start, weekly_totals
from tests.garmin_data import activity_summary


def test_week_starts_on_monday() -> None:
    assert week_start(date(2026, 10, 25)) == date(2026, 10, 19)
    assert week_start(date(2026, 10, 26)) == date(2026, 10, 26)


def test_weekly_totals_group_by_week_and_sport(session: Session) -> None:
    summaries = [
        activity_summary(1, "2026-10-19 07:00:00", distance_m=10_000, elevation_gain_m=500),
        activity_summary(2, "2026-10-25 21:00:00", type_key="ultra_run", distance_m=30_000),
        activity_summary(3, "2026-10-21 07:00:00", type_key="hiking", elevation_gain_m=900),
        activity_summary(4, "2026-10-22 07:00:00", type_key="paddelball"),
        activity_summary(5, "2026-10-26 07:00:00", distance_m=8_000),
    ]
    for summary in summaries:
        raw_store.put_activity(session, summary["activityId"], "summary", summary)
    rebuild_all(session)

    rows = weekly_totals(session, date(2026, 10, 19), date(2026, 10, 26))

    by_key = {(row.week_start, row.sport_group): row for row in rows}
    run_week = by_key[(date(2026, 10, 19), "run")]
    assert run_week.activities == 2
    assert run_week.distance_km == 40.0
    assert run_week.elevation_gain_m == 800
    assert by_key[(date(2026, 10, 19), "vertical")].elevation_gain_m == 900
    assert by_key[(date(2026, 10, 19), "other")].activities == 1
    assert by_key[(date(2026, 10, 26), "run")].distance_km == 8.0
