from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.garmin.source import DAILY_KINDS, GarminRateLimited
from garmin_coach.models import Activity, BodyComposition, DailyWellness, StrengthSet, SyncRun
from garmin_coach.sync import BACKFILL_CURSOR, SyncService, get_state
from tests.garmin_data import FakeGarmin, activity_summary

TODAY = date(2026, 10, 29)


def make_service(garmin: FakeGarmin, sessions: sessionmaker[Session]) -> SyncService:
    return SyncService(
        garmin,
        sessions,
        request_delay=0,
        recent_days=7,
        refresh_days=2,
        today=lambda: TODAY,
        sleep=lambda _: None,
    )


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def garmin() -> FakeGarmin:
    return FakeGarmin(
        [
            activity_summary(1, "2026-10-28 07:00:00"),
            activity_summary(2, "2026-10-20 18:00:00", type_key="strength_training"),
            activity_summary(3, "2026-09-15 09:00:00", type_key="backcountry_skiing"),
        ]
    )


def test_backfill_fetches_activities_days_and_strength_sets(
    garmin: FakeGarmin, sessions: sessionmaker[Session]
) -> None:
    make_service(garmin, sessions).backfill(days=60)

    with sessions() as session:
        assert count(session, Activity) == 3
        assert count(session, DailyWellness) == 61
        assert count(session, StrengthSet) == 3
        expected_endpoints = {"summary", "splits", "hr_zones", "details", "weather"}
        assert raw_store.activity_endpoints(session, 1) == expected_endpoints
        assert "exercise_sets" in raw_store.activity_endpoints(session, 2)
        weather = session.get_one(Activity, 1)
        assert (weather.temperature_c, weather.feels_like_c, weather.humidity_pct) == (10, 5, 80)
        assert count(session, BodyComposition) > 0
        assert get_state(session, BACKFILL_CURSOR) == "2026-08-30"


def test_backfill_resumes_after_rate_limit_without_refetching(
    garmin: FakeGarmin, sessions: sessionmaker[Session]
) -> None:
    garmin.rate_limit_after = 100
    with pytest.raises(GarminRateLimited):
        make_service(garmin, sessions).backfill(days=60)
    calls_before_limit = len(garmin.calls)

    garmin.rate_limit_after = None
    make_service(garmin, sessions).backfill(days=60)

    with sessions() as session:
        assert count(session, Activity) == 3
        assert count(session, DailyWellness) == 61
        runs = session.scalars(select(SyncRun).order_by(SyncRun.id)).all()
        assert [run.status for run in runs] == ["rate_limited", "ok"]
    daily_calls = [args for name, args in garmin.calls if name == "daily"]
    assert len(daily_calls) == len(set(daily_calls))
    assert calls_before_limit == 100


def test_finished_backfill_makes_no_calls_when_run_again(
    garmin: FakeGarmin, sessions: sessionmaker[Session]
) -> None:
    make_service(garmin, sessions).backfill(days=30)
    garmin.calls.clear()

    make_service(garmin, sessions).backfill(days=30)

    assert garmin.calls == []


def test_failed_call_is_not_stored_and_is_retried(
    garmin: FakeGarmin, sessions: sessionmaker[Session]
) -> None:
    garmin.failing.add(("activity", (1, "details")))
    result = make_service(garmin, sessions).backfill(days=10)
    assert result.failed_calls == 1
    with sessions() as session:
        assert "details" not in raw_store.activity_endpoints(session, 1)

    garmin.failing.clear()
    make_service(garmin, sessions).backfill(days=10, restart=True)

    with sessions() as session:
        assert "details" in raw_store.activity_endpoints(session, 1)


def test_recent_sync_refreshes_only_the_last_days(
    garmin: FakeGarmin, sessions: sessionmaker[Session]
) -> None:
    make_service(garmin, sessions).backfill(days=30)
    garmin.calls.clear()

    make_service(garmin, sessions).sync_recent()

    refreshed_days = {args[1] for name, args in garmin.calls if name == "daily"}
    assert refreshed_days == {date(2026, 10, 28), date(2026, 10, 29)}
    assert garmin.count("daily") == 2 * len(DAILY_KINDS)
    refreshed_activities = {args[0] for name, args in garmin.calls if name == "activity"}
    assert refreshed_activities == {1}
