import logging
import threading
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from garmin_coach.garmin.source import GarminError
from garmin_coach.sync import SyncService

log = logging.getLogger(__name__)

SYNC_HOURS = "5-23"
SYNC_MINUTE = 5


class SyncRunner:
    def __init__(self, make_service: Callable[[], SyncService]) -> None:
        self.make_service = make_service
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def run_recent(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self.make_service().sync_recent()
        except GarminError:
            log.exception("Scheduled sync failed")
        finally:
            self._lock.release()
        return True

    def start_in_background(self) -> bool:
        if self.running:
            return False
        threading.Thread(target=self.run_recent, daemon=True).start()
        return True


def start_scheduler(runner: SyncRunner) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        runner.run_recent, "cron", hour=SYNC_HOURS, minute=SYNC_MINUTE, id="recent_sync"
    )
    scheduler.start()
    return scheduler
