from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Goal

TAPER_DAYS = 21
RACE_BRIEF_DAYS = 3
MIN_RACE_ACTIVITY_S = 30 * 60

TAPER_NOTE = """ The race {title} is in {days} days, so this is the taper. Judge today's \
session by whether it helps the race: less volume, short touches of intensity, nothing new. \
Name anything that puts the race at risk, such as pain, signs of illness or several poor \
nights."""

RACE_BRIEF_NOTE = """ The race {title} is in {days} days. After the check-in, write the \
race brief in at most 12 more sentences. Read get_course and get_race_projection for the \
goal, get_fueling for the long sessions of the last 8 weeks, and the notes for earlier race \
lessons. Give a pacing plan with the arrival range at each aid station against the cutoffs, \
where to hold back and where to push, the carbohydrate and fluid per hour that worked in \
training, and the gear and sleep to sort out before the start. Say which parts are rough \
estimates."""

RACE_DAY_PROMPT = """\
Scheduled morning message for {day:%A %d %B}, the day of the race {title}. In at most 4 \
sentences, repeat the first part of the pacing plan and the fueling per hour from the race \
brief, and name one thing from last night's recovery data only if it changes the plan. No \
training advice today."""

RACE_REVIEW_PROMPT = """\
Scheduled race review of activity {id} ({name}, {start:%A %d %B %H:%M}), which is the race \
{title}. Read it with get_activity, and compare it with get_race_projection, get_course and \
the target and cutoffs on the goal. Look at the pace and heart rate across the laps for \
where time went, at the fueling and the rating if I logged them, and at the weather. In at \
most 10 sentences, say what went well, what cost time and what to change for the next \
race. Save each lesson with save_note, starting the text with "Race lesson, {title}". If the \
rating or the fueling log is missing, ask me to fill them in on the Activity page. End with \
how many easy days to take before training again."""


def next_race(session: Session, today: date) -> Goal | None:
    return session.scalars(
        select(Goal)
        .where(Goal.kind == "race", Goal.status == "active", Goal.target_date >= today)
        .order_by(Goal.target_date, Goal.priority)
    ).first()


def race_on(session: Session, day: date) -> Goal | None:
    return session.scalars(
        select(Goal)
        .where(Goal.kind == "race", Goal.status != "dropped", Goal.target_date == day)
        .order_by(Goal.priority)
    ).first()


def days_to(goal: Goal, today: date) -> int:
    assert goal.target_date is not None
    return (goal.target_date - today).days


def race_line(session: Session, today: date) -> str | None:
    goal = next_race(session, today)
    if goal is None:
        return None
    days = days_to(goal, today)
    if days == 0:
        return f"Race day: {goal.title} is today"
    line = f"Next race: {goal.title} in {days} days, on {goal.target_date}"
    return line + (", so this is the taper" if days <= TAPER_DAYS else "")


def brief_due(session: Session, today: date) -> bool:
    goal = next_race(session, today)
    return goal is not None and days_to(goal, today) == RACE_BRIEF_DAYS


def checkin_note(session: Session, today: date) -> str:
    goal = next_race(session, today)
    if goal is None:
        return ""
    days = days_to(goal, today)
    if days == RACE_BRIEF_DAYS:
        return RACE_BRIEF_NOTE.format(title=goal.title, days=days)
    if 0 < days <= TAPER_DAYS:
        return TAPER_NOTE.format(title=goal.title, days=days)
    return ""
