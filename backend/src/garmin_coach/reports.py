from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity
from garmin_coach.normalize.sports import OTHER, sport_groups


@dataclass
class WeekTotals:
    week_start: date
    sport_group: str
    activities: int = 0
    distance_km: float = 0.0
    hours: float = 0.0
    elevation_gain_m: float = 0.0


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_totals(session: Session, first_week: date, last_week: date) -> list[WeekTotals]:
    groups = sport_groups(session)
    activities = session.scalars(
        select(Activity).where(
            Activity.local_date >= first_week,
            Activity.local_date < last_week + timedelta(days=7),
        )
    )
    totals: dict[tuple[date, str], WeekTotals] = {}
    for activity in activities:
        group = groups.get(activity.type_key, OTHER)
        key = (week_start(activity.local_date), group)
        row = totals.setdefault(key, WeekTotals(*key))
        row.activities += 1
        row.distance_km += (activity.distance_m or 0) / 1000
        row.hours += (activity.duration_s or 0) / 3600
        row.elevation_gain_m += activity.elevation_gain_m or 0
    return sorted(totals.values(), key=lambda t: (t.week_start, t.sport_group))


def format_weekly_totals(rows: list[WeekTotals]) -> str:
    by_week: dict[date, list[WeekTotals]] = defaultdict(list)
    for row in rows:
        by_week[row.week_start].append(row)
    lines = []
    for start, week_rows in sorted(by_week.items()):
        iso = start.isocalendar()
        lines.append(f"Week {iso.week} {iso.year} (from {start})")
        for row in week_rows:
            lines.append(
                f"  {row.sport_group:16s} {row.activities:3d} activities "
                f"{row.distance_km:7.1f} km {row.hours:6.1f} h {row.elevation_gain_m:7.0f} m up"
            )
    return "\n".join(lines)
