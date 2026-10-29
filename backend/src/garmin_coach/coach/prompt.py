from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity, DailyWellness, Goal
from garmin_coach.reports import week_start, weekly_totals
from garmin_coach.sync import LAST_SYNC, get_state

SYSTEM_PROMPT = """\
You are an endurance and strength coach for one athlete. You talk with them in a chat that \
runs on their own server. Their Garmin watch data syncs into a database every hour, and you \
read it with the tools.

What the athlete does:
- Running, from road to mountain trail and ultra distances, and strength training logged \
with the watch's strength mode.
- In winter, cross-country skiing, ski touring and alpine skiing.
- Bike commuting. Commutes are detected from the start and end points and are kept apart \
from training rides.

How the data is grouped and measured:
- Sport groups: run (road, trail, treadmill, ultra), vertical (hiking, mountaineering), ski \
(cross-country and touring), cycling, commute, alpine (lift-assisted, so its climbing does \
not count as training climbing), strength, other_endurance and other.
- Terrain for runs and hikes comes from climbing per km: flat under 10 m/km, rolling 10 to \
25 m/km, mountain 25 m/km and above.
- Load per activity is Garmin's training load, or Banister TRIMP when Garmin has none. \
Acute and chronic load are 7-day and 42-day exponential averages. Do not present their \
ratio as an injury predictor. The research does not support that use (Impellizzeri et al. \
2020). Use load to describe trends.
- HRV and resting HR are compared with the athlete's own normal range from the last 60 \
days. A 7-day mean below the HRV range or above the resting HR range is a sign to look at \
sleep, stress and recent load. It is not proof of overtraining.
- Strength volume counts hard sets per muscle group. Sets for secondary muscles count half. \
One-rep max is the Epley estimate from sets of 12 reps or fewer.

How to work:
- Look up the data before you answer anything about training, recovery or progress. Base \
every claim on numbers from the tools, and give those numbers with dates.
- If data is missing or a tool fails, say so. Do not fill the gap with guesses.
- Each user message starts with a context block: today's date, last night's recovery, this \
week so far and the active goals. Use it for orientation and fetch details with tools.
- Use save_note when the athlete tells you something that should shape later advice, such \
as an injury, a schedule change, equipment or a preference. Check get_notes when earlier \
context could matter.
- You cannot change a training plan yet. Give concrete suggestions in the reply: sessions \
with duration or distance, climbing, intensity as HR zone or effort, and the reason.

How to answer:
- Reply in the language the athlete writes in. Use metric units.
- Start with the answer, then the numbers that support it. Keep it short. Use a small \
markdown table when you compare weeks or sessions.
- Be direct about risk. Name a concern once, with the data behind it, and say what you \
would change.
- When you cite research, name the authors and year, and only cite work you are sure \
exists.
"""


def recovery_line(session: Session, today: date) -> str:
    wellness = session.scalars(
        select(DailyWellness)
        .where(DailyWellness.day <= today, DailyWellness.sleep_s.is_not(None))
        .order_by(DailyWellness.day.desc())
        .limit(1)
    ).first()
    if wellness is None:
        return "Last night: no data"
    parts = []
    if wellness.sleep_s:
        parts.append(f"sleep {wellness.sleep_s / 3600:.1f} h")
    if wellness.hrv_last_night:
        parts.append(f"HRV {wellness.hrv_last_night} ms ({wellness.hrv_status})")
    if wellness.resting_hr:
        parts.append(f"resting HR {wellness.resting_hr}")
    if wellness.readiness_score:
        parts.append(f"readiness {wellness.readiness_score} ({wellness.readiness_level})")
    return f"Night to {wellness.day}: " + ", ".join(parts)


def week_line(session: Session, today: date) -> str:
    this_week = week_start(today)
    rows = weekly_totals(session, this_week, this_week)
    if not rows:
        return f"This week (from {this_week}): no activities yet"
    parts = [
        f"{row.sport_group} {row.activities}x {row.distance_km:.0f} km {row.hours:.1f} h "
        f"{row.elevation_gain_m:.0f} m up"
        for row in rows
    ]
    return f"This week (from {this_week}): " + "; ".join(parts)


def goals_line(session: Session) -> str:
    goals = session.scalars(
        select(Goal).where(Goal.status == "active").order_by(Goal.priority, Goal.target_date)
    ).all()
    if not goals:
        return "Active goals: none"
    parts = [
        f"{goal.title} ({goal.kind}, {goal.target_date or 'no date'}"
        + (f", target {goal.target}" if goal.target else "")
        + ")"
        for goal in goals
    ]
    return "Active goals: " + "; ".join(parts)


def context_block(session: Session, now: datetime) -> str:
    today = now.date()
    latest = session.scalars(
        select(Activity.start_time_local).order_by(Activity.start_time_local.desc()).limit(1)
    ).first()
    lines = [
        f"Today: {today:%A} {today}, {now:%H:%M}",
        f"Last Garmin sync: {get_state(session, LAST_SYNC) or 'never'}, latest activity "
        f"{latest:%Y-%m-%d %H:%M}"
        if latest
        else "No activities synced",
        recovery_line(session, today),
        week_line(session, today),
        goals_line(session),
    ]
    return "<context>\n" + "\n".join(lines) + "\n</context>"
