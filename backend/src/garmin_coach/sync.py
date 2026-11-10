import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.garmin.source import (
    ACTIVITY_ENDPOINTS,
    DAILY_KINDS,
    STRENGTH_ENDPOINTS,
    WEATHER_ENDPOINTS,
    GarminAuthError,
    GarminError,
    GarminRateLimited,
    GarminSource,
)
from garmin_coach.metrics.commute import tag_commutes
from garmin_coach.metrics.compliance import match_sessions
from garmin_coach.models import SyncRun, SyncState
from garmin_coach.normalize import normalize_activity, normalize_day
from garmin_coach.normalize.climbs import scan_missing_climbs
from garmin_coach.normalize.sports import seed_sport_mapping, sport_groups

log = logging.getLogger(__name__)

BACKFILL_CHUNK_DAYS = 28
BACKFILL_CURSOR = "backfill_cursor"
LAST_SYNC = "last_sync"


class CallFailed:
    pass


CALL_FAILED = CallFailed()


@dataclass
class SyncResult:
    calls: int = 0
    failed_calls: int = 0
    activities: int = 0
    days: int = 0


def days_between(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def get_state(session: Session, key: str) -> str | None:
    row = session.get(SyncState, key)
    return None if row is None else row.value


def set_state(session: Session, key: str, value: str) -> None:
    session.merge(SyncState(key=key, value=value))


class SyncService:
    def __init__(
        self,
        source: GarminSource,
        sessions: sessionmaker[Session],
        request_delay: float,
        recent_days: int = 14,
        refresh_days: int = 3,
        today: Callable[[], date] = date.today,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source
        self.sessions = sessions
        self.request_delay = request_delay
        self.recent_days = recent_days
        self.refresh_days = refresh_days
        self.today = today
        self.sleep = sleep
        self.result = SyncResult()

    def _call(self, fn: Callable[..., Any], *args: Any) -> Any:
        if self.result.calls > 0:
            self.sleep(self.request_delay)
        self.result.calls += 1
        try:
            return fn(*args)
        except (GarminRateLimited, GarminAuthError):
            raise
        except GarminError as e:
            self.result.failed_calls += 1
            log.warning("%s%s failed: %s", fn.__name__, args, e)
            return CALL_FAILED

    @contextmanager
    def _run(self, kind: str) -> Iterator[None]:
        self.result = SyncResult()
        with self.sessions() as session:
            seed_sport_mapping(session)
            run = SyncRun(kind=kind, started_at=datetime.now(), status="running")
            session.add(run)
            session.commit()
            run_id = run.id
        status, error = "ok", None
        try:
            yield
        except GarminRateLimited as e:
            status, error = "rate_limited", str(e)
            raise
        except GarminAuthError as e:
            status, error = "auth_failed", str(e)
            raise
        except Exception as e:
            status, error = "error", f"{type(e).__name__}: {e}"
            raise
        finally:
            with self.sessions() as session:
                run = session.get_one(SyncRun, run_id)
                run.finished_at = datetime.now()
                run.status = status
                run.error = error
                run.calls = self.result.calls
                run.failed_calls = self.result.failed_calls
                session.commit()

    def _fetch_activity(self, session: Session, summary: dict[str, Any], refresh: bool) -> None:
        activity_id = summary["activityId"]
        raw_store.put_activity(session, activity_id, "summary", summary)
        endpoints = list(ACTIVITY_ENDPOINTS)
        if sport_groups(session).get(summary["activityType"]["typeKey"]) == "strength":
            endpoints += STRENGTH_ENDPOINTS
        if summary.get("startLatitude") is not None:
            endpoints += WEATHER_ENDPOINTS
        have = set() if refresh else raw_store.activity_endpoints(session, activity_id)
        for endpoint in endpoints:
            if endpoint in have:
                continue
            data = self._call(self.source.activity_endpoint, activity_id, endpoint)
            if data is CALL_FAILED and endpoint in WEATHER_ENDPOINTS:
                data = {}
            if data is not CALL_FAILED:
                raw_store.put_activity(session, activity_id, endpoint, data)
                session.commit()
        normalize_activity(session, activity_id)
        session.commit()
        self.result.activities += 1

    def _fetch_day(self, session: Session, day: date, refresh: bool) -> None:
        have = set() if refresh else raw_store.daily_kinds(session, day)
        for kind in DAILY_KINDS:
            if kind in have:
                continue
            data = self._call(self.source.daily, kind, day)
            if data is not CALL_FAILED:
                raw_store.put_daily(session, day, kind, data)
                session.commit()
        normalize_day(session, day)
        session.commit()
        self.result.days += 1

    def _fetch_body_composition(self, session: Session, start: date, end: date) -> None:
        data = self._call(self.source.body_composition, start, end)
        if data is not CALL_FAILED:
            raw_store.put_daily(session, end, "body_composition", data)
            normalize_day(session, end)
            session.commit()

    def _fetch_range(self, start: date, end: date, refresh_from: date | None) -> None:
        with self.sessions() as session:
            summaries = self._call(self.source.list_activities, start, end)
            if summaries is CALL_FAILED:
                raise GarminError(f"Could not list activities from {start} to {end}")
            for summary in summaries:
                local_day = datetime.fromisoformat(summary["startTimeLocal"]).date()
                refresh = refresh_from is not None and local_day >= refresh_from
                self._fetch_activity(session, summary, refresh)
            for day in days_between(start, end):
                refresh = refresh_from is not None and day >= refresh_from
                self._fetch_day(session, day, refresh)
            self._fetch_body_composition(session, start, end)
            tag_commutes(session)
            scan_missing_climbs(session)
            match_sessions(session, start - timedelta(days=1), end + timedelta(days=1))
            session.commit()

    def sync_recent(self) -> SyncResult:
        today = self.today()
        start = today - timedelta(days=self.recent_days - 1)
        refresh_from = today - timedelta(days=self.refresh_days - 1)
        with self._run("recent"):
            self._fetch_range(start, today, refresh_from)
            with self.sessions() as session:
                set_state(session, LAST_SYNC, datetime.now().isoformat(timespec="seconds"))
                session.commit()
        return self.result

    def backfill(self, days: int, restart: bool = False) -> SyncResult:
        oldest = self.today() - timedelta(days=days)
        with self._run("backfill"):
            with self.sessions() as session:
                cursor = None if restart else get_state(session, BACKFILL_CURSOR)
            chunk_end = (
                self.today() if cursor is None else date.fromisoformat(cursor) - timedelta(days=1)
            )
            while chunk_end >= oldest:
                chunk_start = max(oldest, chunk_end - timedelta(days=BACKFILL_CHUNK_DAYS - 1))
                self._fetch_range(chunk_start, chunk_end, refresh_from=None)
                with self.sessions() as session:
                    set_state(session, BACKFILL_CURSOR, chunk_start.isoformat())
                    session.commit()
                log.info(
                    "Backfilled %s to %s: %d calls so far, %d failed",
                    chunk_start,
                    chunk_end,
                    self.result.calls,
                    self.result.failed_calls,
                )
                chunk_end = chunk_start - timedelta(days=1)
        return self.result
