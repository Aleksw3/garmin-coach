import json
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from garmin_coach.metrics.zones import Zone, activity_zone_seconds, current_zones
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
ZONE_TARGET = re.compile(r"\b(?:z|zone)\s*([1-5])(?:\s*(?:-|to)\s*(?:z|zone)?\s*([1-5]))?", re.I)
FIRST_HARD_ZONE = 3
EASY_STEP_KINDS = ("warmup", "cooldown")
# An easy session may spend this share of its time above LT1, on climbs or late in a long
# day, and still count as done as planned. The score reaches zero at the second share.
EASY_SESSION_HARD_SHARE_ALLOWED = 0.10
EASY_SESSION_HARD_SHARE_FAILED = 0.50


def target_zone(text: str | None) -> int | None:
    found = ZONE_TARGET.findall(text or "")
    if not found:
        return None
    return max(int(number) for pair in found for number in pair if number)


def planned_hard_minutes(row: PlannedSession) -> float | None:
    session_zone = target_zone(row.intensity)
    steps: list[dict[str, Any]] = list(row.steps or [])
    if not steps:
        return 0.0 if session_zone is not None and session_zone < FIRST_HARD_ZONE else None
    hard = 0.0
    for step in steps:
        zone = target_zone(step.get("target"))
        if zone is None:
            zone = 1 if step.get("kind") in EASY_STEP_KINDS else session_zone
        if zone is None:
            return None
        if zone < FIRST_HARD_ZONE:
            continue
        if not step.get("duration_min"):
            return None
        hard += step["duration_min"] * (step.get("repeats") or 1)
    return hard


def actual_hard_minutes(session: Session, activity: Activity, zones: list[Zone]) -> float | None:
    seconds = activity_zone_seconds(session, activity.id, zones)
    if sum(seconds) == 0:
        return None
    return sum(seconds[FIRST_HARD_ZONE - 1 :]) / 60


def closeness_to_target(target: float, actual: float) -> float:
    return max(0.0, 1 - abs(actual / target - 1))


def intensity_score(planned_hard: float, actual_hard: float, activity: Activity) -> float:
    if planned_hard > 0:
        return closeness_to_target(planned_hard, actual_hard)
    minutes = (activity.duration_s or 0) / 60
    if minutes == 0:
        return 1.0
    over = actual_hard / minutes - EASY_SESSION_HARD_SHARE_ALLOWED
    span = EASY_SESSION_HARD_SHARE_FAILED - EASY_SESSION_HARD_SHARE_ALLOWED
    return 1 - min(max(over / span, 0.0), 1.0)


def compliance(
    row: PlannedSession, activity: Activity, hard_minutes: float | None = None
) -> tuple[float | None, dict[str, list[float]]]:
    pairs = {
        "duration_min": (row.duration_min, (activity.duration_s or 0) / 60),
        "distance_km": (row.distance_km, (activity.distance_m or 0) / 1000),
        "elevation_gain_m": (row.elevation_gain_m, activity.elevation_gain_m or 0),
    }
    details = {
        name: [target, round(actual, 1)] for name, (target, actual) in pairs.items() if target
    }
    scores = [closeness_to_target(target, actual) for target, actual in details.values()]
    planned_hard = planned_hard_minutes(row) if hard_minutes is not None else None
    if planned_hard is not None and hard_minutes is not None:
        details["hard_min"] = [round(planned_hard, 1), round(hard_minutes, 1)]
        scores.append(intensity_score(planned_hard, hard_minutes, activity))
    if not scores:
        return None, details
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
    zones = current_zones(session)
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
    neighbours = session.scalars(
        select(PlannedSession).where(
            PlannedSession.day >= first - timedelta(days=1),
            PlannedSession.day <= last + timedelta(days=1),
        )
    ).all()

    def planned_on_its_day(activity: Activity) -> bool:
        group = groups.get(activity.type_key, OTHER)
        return any(
            p.day == activity.local_date and group in MATCHING_GROUPS.get(p.sport, set())
            for p in neighbours
        )

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
                and (days_apart == 0 or not planned_on_its_day(a))
            ]
            if not candidates:
                continue
            activity = max(candidates, key=lambda a: closeness(row, a))
            hard = (
                actual_hard_minutes(session, activity, zones)
                if zones and row.sport != "strength"
                else None
            )
            score, details = compliance(row, activity, hard)
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
