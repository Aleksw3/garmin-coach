from sqlalchemy.orm import Session

from garmin_coach import raw_store
from garmin_coach.normalize.activities import normalize_activity
from garmin_coach.normalize.daily import normalize_day


def rebuild_all(session: Session) -> tuple[int, int]:
    activity_ids = raw_store.activity_ids(session)
    for activity_id in activity_ids:
        normalize_activity(session, activity_id)
    days = raw_store.daily_days(session)
    for day in days:
        normalize_day(session, day)
    return len(activity_ids), len(days)


__all__ = ["normalize_activity", "normalize_day", "rebuild_all"]
