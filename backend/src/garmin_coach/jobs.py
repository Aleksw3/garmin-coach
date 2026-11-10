import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from garmin_coach.coach.proactive import ProactiveCoach
from garmin_coach.evidence.fetch import EvidenceFetcher
from garmin_coach.garmin.nightly import TomorrowOnWatch
from garmin_coach.garmin.source import GarminAuthError, GarminError
from garmin_coach.sync import SyncService

log = logging.getLogger(__name__)

SYNC_HOURS = "5-23"
SYNC_MINUTE = 5
SYNC_SPACING_MIN = 10
CHECKIN_WAIT_HOURS = 2


@dataclass(frozen=True)
class Backfill:
    days: int
    started_at: datetime


class SyncRunner:
    def __init__(
        self,
        make_service: Callable[[], SyncService],
        on_synced: Callable[[], object] | None = None,
        on_auth_failed: Callable[[str], object] | None = None,
    ) -> None:
        self.make_service = make_service
        self.on_synced = on_synced
        self.on_auth_failed = on_auth_failed
        self.backfill: Backfill | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def _guarded(self, work: Callable[[SyncService], object]) -> bool:
        try:
            work(self.make_service())
            return True
        except GarminAuthError as error:
            log.exception("Garmin login failed")
            if self.on_auth_failed:
                self.on_auth_failed(str(error))
        except GarminError:
            log.exception("Sync failed")
        return False

    def run_recent(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            synced = self._guarded(lambda service: service.sync_recent())
        finally:
            self._lock.release()
        if synced and self.on_synced:
            threading.Thread(target=self.on_synced, daemon=True).start()
        return True

    def start_in_background(self) -> bool:
        if self.running:
            return False
        threading.Thread(target=self.run_recent, daemon=True).start()
        return True

    def start_backfill(self, days: int) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        self.backfill = Backfill(days, datetime.now())
        threading.Thread(target=self._run_backfill, args=(days,), daemon=True).start()
        return True

    def _run_backfill(self, days: int) -> None:
        try:
            self._guarded(lambda service: service.backfill(days))
        finally:
            self.backfill = None
            self._lock.release()


@dataclass(frozen=True)
class Schedule:
    checkin_time: str = "06:30"
    review_day: str = "sun"
    review_time: str = "19:00"
    evidence_day: str = "mon"
    evidence_time: str = "07:00"
    watch_time: str = "20:00"
    backup_time: str = "03:30"


DEFAULT_SCHEDULE = Schedule()


def hour_minute(clock: str) -> tuple[int, int]:
    hour, minute = clock.split(":")
    return int(hour), int(minute)


@dataclass(frozen=True)
class ScheduledProfile:
    slug: str
    runner: SyncRunner
    proactive: ProactiveCoach | None = None
    watch: TomorrowOnWatch | None = None


def sync_then_checkin(runner: SyncRunner, proactive: ProactiveCoach) -> None:
    proactive.expect_checkin()
    runner.run_recent()


def schedule_profile(
    scheduler: BackgroundScheduler,
    profile: ScheduledProfile,
    index: int,
    schedule: Schedule = DEFAULT_SCHEDULE,
) -> None:
    scheduler.add_job(
        profile.runner.run_recent,
        "cron",
        hour=SYNC_HOURS,
        minute=(SYNC_MINUTE + index * SYNC_SPACING_MIN) % 60,
        id=f"recent_sync_{profile.slug}",
    )
    if profile.watch is not None:
        hour, minute = hour_minute(schedule.watch_time)
        scheduler.add_job(
            profile.watch.send,
            "cron",
            hour=hour,
            minute=minute,
            id=f"tomorrow_on_watch_{profile.slug}",
        )
    proactive = profile.proactive
    if proactive is None:
        return
    hour, minute = hour_minute(schedule.checkin_time)
    scheduler.add_job(
        lambda: sync_then_checkin(profile.runner, proactive),
        "cron",
        hour=hour,
        minute=minute,
        id=f"morning_checkin_{profile.slug}",
    )
    scheduler.add_job(
        proactive.checkin_deadline,
        "cron",
        hour=(hour + CHECKIN_WAIT_HOURS) % 24,
        minute=minute,
        id=f"checkin_deadline_{profile.slug}",
    )
    hour, minute = hour_minute(schedule.review_time)
    scheduler.add_job(
        proactive.weekly_review,
        "cron",
        day_of_week=schedule.review_day,
        hour=hour,
        minute=minute,
        id=f"weekly_review_{profile.slug}",
    )


def start_scheduler(
    profiles: list[ScheduledProfile],
    schedule: Schedule = DEFAULT_SCHEDULE,
    fetcher: EvidenceFetcher | None = None,
    backup: Callable[[], object] | None = None,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    for index, profile in enumerate(profiles):
        schedule_profile(scheduler, profile, index, schedule)
    if backup is not None:
        hour, minute = hour_minute(schedule.backup_time)
        scheduler.add_job(backup, "cron", hour=hour, minute=minute, id="backup")
    if fetcher is not None:
        hour, minute = hour_minute(schedule.evidence_time)
        scheduler.add_job(
            fetcher.fetch_all,
            "cron",
            day_of_week=schedule.evidence_day,
            hour=hour,
            minute=minute,
            id="evidence_fetch",
        )
    scheduler.start()
    return scheduler
