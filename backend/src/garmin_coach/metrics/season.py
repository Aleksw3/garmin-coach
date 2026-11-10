from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity, SeasonWeek
from garmin_coach.normalize.sports import OTHER, sport_groups
from garmin_coach.reports import week_start

ON_FOOT_GROUPS = ("run", "vertical")


@dataclass
class WeekDone:
    hours: float = 0.0
    climb_m: float = 0.0
    longest_h: float = 0.0


@dataclass
class SeasonProgress:
    week: SeasonWeek
    done: WeekDone


def weeks_done(session: Session, first_week: date, last_week: date) -> dict[date, WeekDone]:
    groups = sport_groups(session)
    done: dict[date, WeekDone] = {}
    activities = session.scalars(
        select(Activity).where(
            Activity.local_date >= first_week,
            Activity.local_date < last_week + timedelta(days=7),
        )
    )
    for activity in activities:
        if activity.is_commute:
            continue
        week = done.setdefault(week_start(activity.local_date), WeekDone())
        hours = (activity.duration_s or 0) / 3600
        week.hours += hours
        if groups.get(activity.type_key, OTHER) in ON_FOOT_GROUPS:
            week.climb_m += activity.elevation_gain_m or 0
            week.longest_h = max(week.longest_h, hours)
    return done


def season_progress(session: Session, first: date, last: date) -> list[SeasonProgress]:
    weeks = session.scalars(
        select(SeasonWeek)
        .where(SeasonWeek.week_start >= week_start(first), SeasonWeek.week_start <= last)
        .order_by(SeasonWeek.week_start)
    ).all()
    if not weeks:
        return []
    done = weeks_done(session, weeks[0].week_start, weeks[-1].week_start)
    return [SeasonProgress(week, done.get(week.week_start, WeekDone())) for week in weeks]


def week_targets(week: SeasonWeek) -> str:
    parts = [f"{week.hours:g} h"]
    if week.climb_m is not None:
        parts.append(f"{week.climb_m:.0f} m climbing on foot")
    if week.longest_h is not None:
        parts.append(f"longest run or hike {week.longest_h:g} h")
    return ", ".join(parts)


def season_line(session: Session, today: date) -> str | None:
    progress = season_progress(session, today, today)
    if not progress:
        return None
    week, done = progress[0].week, progress[0].done
    return (
        f"Season outline this week: {week.phase} phase, targets {week_targets(week)}. "
        f"Done so far: {done.hours:.1f} h, {done.climb_m:.0f} m climbing on foot, "
        f"longest {done.longest_h:.1f} h" + (f". Focus: {week.focus}" if week.focus else "")
    )
