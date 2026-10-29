from datetime import date, timedelta

from sqlalchemy.orm import Session

from garmin_coach.metrics.load import training_load
from garmin_coach.metrics.recovery import hrv_baseline, resting_hr_baseline
from garmin_coach.metrics.running import run_weeks
from garmin_coach.metrics.strength import (
    best_one_rep_max,
    effective_sets,
    is_hard_set,
    is_single_leg_or_eccentric,
    weekly_sets_per_muscle,
)

LOWER_BODY = ("quads", "hamstrings", "glutes", "calves")


def load_lines(session: Session, first_week: date, last: date, coefficient: float) -> list[str]:
    series = training_load(session, first_week, last, coefficient)
    if not series:
        return ["Training load: no data"]
    today = series[-1]
    lines = [
        f"Training load on {today.day}: acute (7-day) {today.acute:.0f}, "
        f"chronic (42-day) {today.chronic:.0f}"
    ]
    for index in range(0, len(series), 7):
        week = series[index : index + 7]
        lines.append(f"  week from {week[0].day}: load {sum(d.load for d in week):.0f}")
    return lines


def recovery_lines(session: Session, last: date) -> list[str]:
    hrv = hrv_baseline(session, last, last)
    resting = resting_hr_baseline(session, last)
    lines = []
    if hrv:
        status = hrv[-1]
        lines.append(
            f"HRV (ln rMSSD) 7-day mean {status.rolling:.2f}, normal range "
            f"{status.low:.2f} to {status.high:.2f}: {status.status}"
        )
    else:
        lines.append("HRV: not enough data for a baseline")
    if resting:
        lines.append(
            f"Resting HR 7-day mean {resting.rolling:.1f}, normal range "
            f"{resting.low:.1f} to {resting.high:.1f}: {resting.status}"
        )
    return lines


def running_lines(session: Session, first_week: date, last_week: date) -> list[str]:
    lines = ["Running (terrain hours: flat / rolling / mountain)"]
    for week in run_weeks(session, first_week, last_week):
        terrain = week.hours_by_terrain
        lines.append(
            f"  week from {week.week_start}: {week.runs} runs, {week.distance_km:.1f} km, "
            f"{week.hours:.1f} h, {week.elevation_gain_m:.0f} m up, "
            f"{week.elevation_loss_m:.0f} m down, longest {week.longest_run_h:.1f} h, "
            f"terrain {terrain['flat']:.1f} / {terrain['rolling']:.1f} / "
            f"{terrain['mountain']:.1f}, back-to-back long days {week.back_to_back_long_days}"
        )
    return lines


def strength_lines(session: Session, first_week: date, last: date) -> list[str]:
    lines = ["Strength: hard sets per muscle group (secondary muscles count half)"]
    weekly = weekly_sets_per_muscle(session, first_week, last - timedelta(days=last.weekday()))
    for week, muscles in weekly.items():
        lower = ", ".join(f"{m} {muscles.get(m, 0):g}" for m in LOWER_BODY)
        others = ", ".join(
            f"{m} {count:g}" for m, count in sorted(muscles.items()) if m not in LOWER_BODY
        )
        lines.append(f"  week from {week}: {lower}; {others or 'no upper body or core'}")
    sets = effective_sets(session, first_week, last)
    single_leg = sum(1 for s in sets if is_hard_set(s) and is_single_leg_or_eccentric(s))
    lines.append(f"  single-leg or eccentric hard sets: {single_leg}")
    for exercise, (day, estimate) in sorted(best_one_rep_max(sets).items()):
        lines.append(f"  best estimated 1RM {exercise}: {estimate:.1f} kg on {day}")
    return lines


def format_metrics(session: Session, weeks: int, last: date, trimp_coefficient: float) -> str:
    last_week = last - timedelta(days=last.weekday())
    first_week = last_week - timedelta(weeks=weeks - 1)
    sections = [
        load_lines(session, first_week, last, trimp_coefficient),
        recovery_lines(session, last),
        running_lines(session, first_week, last_week),
        strength_lines(session, first_week, last),
    ]
    return "\n\n".join("\n".join(section) for section in sections)
