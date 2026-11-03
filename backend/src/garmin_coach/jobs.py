import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from apscheduler.schedulers.background import BackgroundScheduler

from garmin_coach.coach.proactive import ProactiveCoach
from garmin_coach.evidence.fetch import EvidenceFetcher
from garmin_coach.garmin.source import GarminAuthError, GarminError
from garmin_coach.sync import SyncService

log = logging.getLogger(__name__)

SYNC_HOURS = "5-23"
SYNC_MINUTE = 5
SYNC_SPACING_MIN = 10


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
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def run_recent(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        synced = False
        try:
            self.make_service().sync_recent()
            synced = True
        except GarminAuthError as error:
            log.exception("Garmin login failed")
            if self.on_auth_failed:
                self.on_auth_failed(str(error))
        except GarminError:
            log.exception("Scheduled sync failed")
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


@dataclass(frozen=True)
class Schedule:
    checkin_time: str = "06:30"
    review_day: str = "sun"
    review_time: str = "19:00"
    evidence_day: str = "mon"
    evidence_time: str = "07:00"


DEFAULT_SCHEDULE = Schedule()


def hour_minute(clock: str) -> tuple[int, int]:
    hour, minute = clock.split(":")
    return int(hour), int(minute)


@dataclass(frozen=True)
class ScheduledProfile:
    slug: str
    runner: SyncRunner
    proactive: ProactiveCoach | None = None


def start_scheduler(
    profiles: list[ScheduledProfile],
    schedule: Schedule = DEFAULT_SCHEDULE,
    fetcher: EvidenceFetcher | None = None,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    for index, profile in enumerate(profiles):
        scheduler.add_job(
            profile.runner.run_recent,
            "cron",
            hour=SYNC_HOURS,
            minute=(SYNC_MINUTE + index * SYNC_SPACING_MIN) % 60,
            id=f"recent_sync_{profile.slug}",
        )
        if profile.proactive is None:
            continue
        hour, minute = hour_minute(schedule.checkin_time)
        scheduler.add_job(
            profile.proactive.morning_checkin,
            "cron",
            hour=hour,
            minute=minute,
            id=f"morning_checkin_{profile.slug}",
        )
        hour, minute = hour_minute(schedule.review_time)
        scheduler.add_job(
            profile.proactive.weekly_review,
            "cron",
            day_of_week=schedule.review_day,
            hour=hour,
            minute=minute,
            id=f"weekly_review_{profile.slug}",
        )
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
