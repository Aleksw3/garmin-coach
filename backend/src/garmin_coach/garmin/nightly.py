import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.notify import Sender
from garmin_coach.coach.plan import sessions_between
from garmin_coach.garmin.source import GarminError, GarminSource
from garmin_coach.garmin.workouts import fits_on_watch, send_to_watch
from garmin_coach.metrics.zones import current_zones

log = logging.getLogger(__name__)


class TomorrowOnWatch:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        make_source: Callable[[], GarminSource],
        notifier: Sender,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.sessions = sessions
        self.make_source = make_source
        self.notifier = notifier
        self.today = today
        self.now = now

    def send(self) -> list[str]:
        tomorrow = self.today() + timedelta(days=1)
        sent: list[str] = []
        with self.sessions() as session:
            waiting = [
                row
                for row in sessions_between(session, tomorrow, tomorrow)
                if fits_on_watch(row) and not row.skipped and row.garmin_workout_id is None
            ]
            if not waiting:
                return sent
            zones = current_zones(session)
            source = self.make_source()
            for row in waiting:
                try:
                    send_to_watch(source, row, zones, self.now())
                except GarminError as error:
                    log.exception("Sending planned session %s to the watch failed", row.id)
                    self.notifier.send(
                        "Tomorrow's session is not on the watch",
                        f"Garmin did not take {row.title}: {error}. Open it on the Plan page "
                        "and press Send to watch.",
                        "#plan",
                    )
                    return sent
                session.commit()
                sent.append(row.title)
        verb = "is" if len(sent) == 1 else "are"
        self.notifier.send(
            "Tomorrow's training is on the watch",
            f"{' and '.join(sent)} {verb} in the Garmin calendar for tomorrow. Open the Garmin "
            "Connect app so the watch syncs before you start.",
            "#plan",
        )
        return sent
