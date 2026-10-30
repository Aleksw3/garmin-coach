import json
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity, PlannedSession, SessionMatch
from garmin_coach.normalize.sports import OTHER, sport_groups

MATCHING_GROUPS = {
    "run": {"run", "vertical"},
    "vertical": {"vertical", "run"},
    "ski": {"ski"},
    "cycling": {"cycling"},
    "strength": {"strength"},
    "other": {"other_endurance", "other", "alpine", "ski", "cycling"},
}


def compliance(
    row: PlannedSession, activity: Activity
) -> tuple[float | None, dict[str, list[float]]]:
    pairs = {
        "duration_min": (row.duration_min, (activity.duration_s or 0) / 60),
        "distance_km": (row.distance_km, (activity.distance_m or 0) / 1000),
        "elevation_gain_m": (row.elevation_gain_m, activity.elevation_gain_m or 0),
    }
    details = {
        name: [target, round(actual, 1)] for name, (target, actual) in pairs.items() if target
    }
    if not details:
        return None, details
    scores = [max(0.0, 1 - abs(actual / target - 1)) for target, actual in details.values()]
    return round(100 * sum(scores) / len(scores)), details


def closeness(row: PlannedSession, activity: Activity) -> float:
    if row.duration_min:
        return -abs((activity.duration_s or 0) / 60 - row.duration_min)
    return activity.duration_s or 0


def match_sessions(session: Session, first: date, last: date) -> int:
    rows = list(
        session.scalars(
            select(PlannedSession)
            .where(PlannedSession.day >= first, PlannedSession.day <= last)
            .order_by(PlannedSession.day, PlannedSession.id)
        )
    )
    session.execute(
        delete(SessionMatch).where(SessionMatch.planned_session_id.in_([r.id for r in rows]))
    )
    taken = set(session.scalars(select(SessionMatch.activity_id)))
    groups = sport_groups(session)
    activities = [
        activity
        for activity in session.scalars(
            select(Activity).where(
                Activity.local_date >= first - timedelta(days=1),
                Activity.local_date <= last + timedelta(days=1),
            )
        )
        if not activity.is_commute and activity.id not in taken
    ]
    open_rows = [r for r in rows if not r.skipped and r.sport in MATCHING_GROUPS]
    matched = 0
    for days_apart in (0, 1):
        for row in list(open_rows):
            candidates = [
                a
                for a in activities
                if a.id not in taken
                and groups.get(a.type_key, OTHER) in MATCHING_GROUPS[row.sport]
                and abs((a.local_date - row.day).days) == days_apart
            ]
            if not candidates:
                continue
            activity = max(candidates, key=lambda a: closeness(row, a))
            score, details = compliance(row, activity)
            session.add(
                SessionMatch(
                    planned_session_id=row.id,
                    activity_id=activity.id,
                    compliance=score,
                    details=json.dumps(details),
                )
            )
            taken.add(activity.id)
            open_rows.remove(row)
            matched += 1
    session.flush()
    return matched


def match_all(session: Session) -> int:
    days = session.scalars(select(PlannedSession.day).order_by(PlannedSession.day)).all()
    return match_sessions(session, days[0], days[-1]) if days else 0
