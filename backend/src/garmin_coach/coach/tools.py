import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from garmin_coach.metrics.load import training_load
from garmin_coach.metrics.recovery import hrv_baseline, resting_hr_baseline
from garmin_coach.metrics.running import climb_per_km, terrain
from garmin_coach.metrics.strength import effective_sets
from garmin_coach.metrics.summary import running_lines, strength_lines
from garmin_coach.models import (
    Activity,
    ActivityLap,
    ActivityZoneTime,
    AthleteProfile,
    CoachNote,
    DailyWellness,
    Goal,
)
from garmin_coach.normalize.sports import OTHER, sport_groups
from garmin_coach.reports import format_weekly_totals, week_start, weekly_totals
from garmin_coach.sync import LAST_SYNC, get_state

log = logging.getLogger(__name__)

MAX_RANGE_DAYS = 731
MAX_WELLNESS_DAYS = 92
MAX_ACTIVITIES = 150
MAX_LAPS = 40
MAX_NOTES = 50
TERRAIN_GROUPS = ("run", "vertical")


@dataclass
class ToolContext:
    session: Session
    today: date
    trimp_coefficient: float


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DateRange(ToolInput):
    start: date = Field(description="First day, YYYY-MM-DD")
    end: date = Field(description="Last day, YYYY-MM-DD, inclusive")

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if self.start > self.end:
            raise ValueError("start is after end")
        if (self.end - self.start).days > MAX_RANGE_DAYS:
            raise ValueError(f"range is longer than {MAX_RANGE_DAYS} days")
        return self


class ActivityQuery(DateRange):
    sport_group: str | None = Field(
        default=None,
        description="Only this group: run, vertical, ski, cycling, commute, alpine, strength, "
        "other_endurance or other",
    )


class ActivityId(ToolInput):
    activity_id: int


class WellnessRange(DateRange):
    @model_validator(mode="after")
    def check_length(self) -> Self:
        if (self.end - self.start).days >= MAX_WELLNESS_DAYS:
            raise ValueError(f"wellness range is limited to {MAX_WELLNESS_DAYS} days")
        return self


class NoteQuery(ToolInput):
    query: str | None = Field(default=None, description="Only notes containing this text")


class NewNote(ToolInput):
    text: str = Field(min_length=1, max_length=1000)


def hours_minutes(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    minutes = round(seconds / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def number(value: float | None, unit: str, digits: int = 0) -> str | None:
    return None if value is None else f"{value:.{digits}f} {unit}"


def pace(speed_mps: float | None) -> str | None:
    if not speed_mps:
        return None
    seconds = 1000 / speed_mps
    return f"{int(seconds // 60)}:{round(seconds % 60):02d} /km"


def joined(parts: list[str | None]) -> str:
    return " | ".join(part for part in parts if part)


def activity_group(activity: Activity, groups: dict[str, str]) -> str:
    return "commute" if activity.is_commute else groups.get(activity.type_key, OTHER)


def activity_line(activity: Activity, groups: dict[str, str]) -> str:
    group = activity_group(activity, groups)
    climb = climb_per_km(activity.elevation_gain_m, activity.distance_m)
    return joined(
        [
            f"id {activity.id}",
            activity.start_time_local.strftime("%Y-%m-%d %H:%M"),
            f"{activity.type_key} ({group})",
            activity.name,
            number(None if activity.distance_m is None else activity.distance_m / 1000, "km", 1),
            f"{hours_minutes(activity.duration_s)} h",
            number(activity.elevation_gain_m, "m up"),
            number(activity.avg_hr, "bpm avg"),
            number(activity.training_load, "load"),
            f"terrain {terrain(climb)}" if group in TERRAIN_GROUPS and climb is not None else None,
        ]
    )


def list_activities(ctx: ToolContext, args: ActivityQuery) -> str:
    groups = sport_groups(ctx.session)
    activities = [
        activity
        for activity in ctx.session.scalars(
            select(Activity)
            .where(Activity.local_date >= args.start, Activity.local_date <= args.end)
            .order_by(Activity.start_time_local.desc())
        )
        if args.sport_group is None or activity_group(activity, groups) == args.sport_group
    ]
    header = f"{len(activities)} activities from {args.start} to {args.end}, newest first"
    if len(activities) > MAX_ACTIVITIES:
        header += f". Showing the newest {MAX_ACTIVITIES}, ask for a shorter range for the rest"
    lines = [activity_line(a, groups) for a in activities[:MAX_ACTIVITIES]]
    return "\n".join([header, *lines])


def get_activity(ctx: ToolContext, args: ActivityId) -> str:
    activity = ctx.session.get(Activity, args.activity_id)
    if activity is None:
        raise LookupError(f"No activity with id {args.activity_id}")
    groups = sport_groups(ctx.session)
    lines = [
        activity_line(activity, groups),
        joined(
            [
                number(activity.elevation_loss_m, "m down"),
                f"moving {hours_minutes(activity.moving_s)} h" if activity.moving_s else None,
                number(activity.max_hr, "bpm max"),
                f"pace {pace(activity.avg_speed_mps)}" if activity.distance_m else None,
                f"grade-adjusted {pace(activity.avg_grade_adjusted_speed_mps)}"
                if activity.avg_grade_adjusted_speed_mps
                else None,
                number(activity.avg_power_w, "W avg"),
                number(activity.aerobic_training_effect, "aerobic TE", 1),
                number(activity.anaerobic_training_effect, "anaerobic TE", 1),
                activity.training_effect_label,
            ]
        ),
    ]
    zones = ctx.session.scalars(
        select(ActivityZoneTime)
        .where(ActivityZoneTime.activity_id == activity.id)
        .order_by(ActivityZoneTime.kind, ActivityZoneTime.zone)
    ).all()
    for kind in ("hr", "power"):
        kind_zones = [z for z in zones if z.kind == kind]
        if kind_zones:
            lines.append(
                f"Time in {kind} zones: "
                + ", ".join(f"Z{z.zone} {hours_minutes(z.seconds)}" for z in kind_zones)
            )
    laps = ctx.session.scalars(
        select(ActivityLap)
        .where(ActivityLap.activity_id == activity.id)
        .order_by(ActivityLap.lap_index)
    ).all()
    if laps:
        lines.append(f"Laps ({len(laps)}, showing up to {MAX_LAPS}):")
        for lap in laps[:MAX_LAPS]:
            lines.append(
                "  "
                + joined(
                    [
                        f"lap {lap.lap_index + 1}",
                        number(None if lap.distance_m is None else lap.distance_m / 1000, "km", 2),
                        f"{hours_minutes(lap.duration_s)}",
                        pace(lap.avg_speed_mps),
                        number(lap.elevation_gain_m, "m up"),
                        number(lap.elevation_loss_m, "m down"),
                        number(lap.avg_hr, "bpm"),
                        lap.intensity_type,
                    ]
                )
            )
    sets = [
        s
        for s in effective_sets(ctx.session, activity.local_date, activity.local_date)
        if s.activity_id == activity.id
    ]
    if sets:
        lines.append("Strength sets:")
        for s in sets:
            weight = f" x {s.weight_kg:g} kg" if s.weight_kg else ""
            lines.append(f"  {s.category}/{s.name}: {s.reps or '?'} reps{weight}")
    return "\n".join(lines)


def get_weekly_summary(ctx: ToolContext, args: DateRange) -> str:
    rows = weekly_totals(ctx.session, week_start(args.start), week_start(args.end))
    return format_weekly_totals(rows) or "No activities in this range"


def get_running_weeks(ctx: ToolContext, args: DateRange) -> str:
    return "\n".join(running_lines(ctx.session, week_start(args.start), week_start(args.end)))


def get_strength(ctx: ToolContext, args: DateRange) -> str:
    return "\n".join(strength_lines(ctx.session, week_start(args.start), args.end))


def get_load(ctx: ToolContext, args: DateRange) -> str:
    series = training_load(ctx.session, args.start, args.end, ctx.trimp_coefficient)
    if not series:
        return "No load data in this range"
    lines = ["Weekly load sum, then acute (7-day) and chronic (42-day) averages at week end"]
    by_week: dict[date, list[float]] = {}
    for entry in series:
        by_week.setdefault(week_start(entry.day), []).append(entry.load)
    last_by_week = {week_start(entry.day): entry for entry in series}
    for week, loads in by_week.items():
        last = last_by_week[week]
        lines.append(
            f"  week from {week}: load {sum(loads):.0f}, acute {last.acute:.0f}, "
            f"chronic {last.chronic:.0f}"
        )
    return "\n".join(lines)


def get_wellness(ctx: ToolContext, args: WellnessRange) -> str:
    rows = ctx.session.scalars(
        select(DailyWellness)
        .where(DailyWellness.day >= args.start, DailyWellness.day <= args.end)
        .order_by(DailyWellness.day)
    )
    lines = []
    for w in rows:
        sleep = None
        if w.sleep_s:
            sleep = f"sleep {w.sleep_s / 3600:.1f} h" + (
                f" (score {w.sleep_score})" if w.sleep_score else ""
            )
        lines.append(
            joined(
                [
                    str(w.day),
                    sleep,
                    f"HRV {w.hrv_last_night} ms ({w.hrv_status})" if w.hrv_last_night else None,
                    number(w.resting_hr, "bpm resting"),
                    f"readiness {w.readiness_score} {w.readiness_level}"
                    if w.readiness_score
                    else None,
                    f"body battery at wake {w.body_battery_at_wake}"
                    if w.body_battery_at_wake
                    else None,
                    number(w.avg_stress, "avg stress"),
                    f"training status {w.training_status}" if w.training_status else None,
                    number(w.vo2max, "VO2max", 1),
                ]
            )
        )
    hrv = hrv_baseline(ctx.session, args.end, args.end)
    if hrv:
        status = hrv[-1]
        lines.append(
            f"HRV 7-day mean on {status.day}: {math.exp(status.rolling):.0f} ms, normal range "
            f"from the last 60 days {math.exp(status.low):.0f} to {math.exp(status.high):.0f} ms: "
            f"{status.status}"
        )
    resting = resting_hr_baseline(ctx.session, args.end)
    if resting:
        lines.append(
            f"Resting HR 7-day mean: {resting.rolling:.1f} bpm, normal range "
            f"{resting.low:.1f} to {resting.high:.1f}: {resting.status}"
        )
    return "\n".join(lines) or "No wellness data in this range"


def profile_text(profile: AthleteProfile | None) -> list[str]:
    if profile is None:
        return ["The athlete has not filled in a profile yet."]
    fields = {
        "Name": profile.name,
        "Birth year": profile.birth_year,
        "Sex": profile.sex,
        "Height": None if profile.height_cm is None else f"{profile.height_cm:g} cm",
        "Max HR": profile.max_hr,
        "Training days": profile.training_days,
        "Injuries": profile.injuries,
        "Equipment": profile.equipment,
        "Notes": profile.notes,
    }
    return [f"{key}: {value}" for key, value in fields.items() if value not in (None, "")]


def get_profile(ctx: ToolContext, _args: ToolInput) -> str:
    first, last = ctx.session.execute(
        select(func.min(Activity.local_date), func.max(Activity.local_date))
    ).one()
    lines = profile_text(ctx.session.get(AthleteProfile, 1))
    lines.append(f"Activities in the database: {first} to {last}")
    lines.append(f"Last Garmin sync: {get_state(ctx.session, LAST_SYNC) or 'never'}")
    return "\n".join(lines)


def goal_text(goal: Goal) -> str:
    return joined(
        [
            f"goal {goal.id}",
            f"{goal.kind}, priority {goal.priority}, {goal.status}",
            goal.title,
            f"date {goal.target_date}" if goal.target_date else None,
            f"target {goal.target}" if goal.target else None,
            number(goal.distance_km, "km", 1),
            number(goal.elevation_gain_m, "m climbing"),
            f"terrain: {goal.terrain}" if goal.terrain else None,
            f"cutoffs: {goal.cutoffs}" if goal.cutoffs else None,
            f"notes: {goal.notes}" if goal.notes else None,
        ]
    )


def get_goals(ctx: ToolContext, _args: ToolInput) -> str:
    goals = ctx.session.scalars(select(Goal).order_by(Goal.status, Goal.priority, Goal.id)).all()
    return "\n".join(goal_text(g) for g in goals) or "No goals set"


def get_notes(ctx: ToolContext, args: NoteQuery) -> str:
    query = select(CoachNote).order_by(CoachNote.created_at.desc()).limit(MAX_NOTES)
    if args.query:
        query = query.where(CoachNote.text.icontains(args.query))
    notes = ctx.session.scalars(query).all()
    return "\n".join(f"{n.created_at:%Y-%m-%d}: {n.text}" for n in notes) or "No notes"


def save_note(ctx: ToolContext, args: NewNote) -> str:
    note = CoachNote(created_at=datetime.now(), text=args.text)
    ctx.session.add(note)
    ctx.session.flush()
    return f"Saved note {note.id}"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[ToolInput]
    handler: Callable[[ToolContext, Any], str]


TOOLS = (
    Tool(
        "get_activity",
        "One activity in detail: pace, grade-adjusted pace, HR and power zones, laps and "
        "strength sets with reps and weight.",
        ActivityId,
        get_activity,
    ),
    Tool(
        "get_goals", "The athlete's goals, including race details and status.", ToolInput, get_goals
    ),
    Tool(
        "get_load",
        "Training load per week with acute (7-day) and chronic (42-day) exponential averages.",
        DateRange,
        get_load,
    ),
    Tool(
        "get_notes",
        "Notes saved in earlier conversations, such as injuries, preferences and life events.",
        NoteQuery,
        get_notes,
    ),
    Tool(
        "get_profile",
        "The athlete's profile (age, max HR, training days, injuries, equipment) and how far "
        "back the data goes.",
        ToolInput,
        get_profile,
    ),
    Tool(
        "get_running_weeks",
        "Running and hiking per week: distance, time, climbing and descent, longest run, hours "
        "on flat, rolling and mountain terrain, and back-to-back long days.",
        DateRange,
        get_running_weeks,
    ),
    Tool(
        "get_strength",
        "Strength per week: hard sets per muscle group, single-leg and eccentric sets, and the "
        "best estimated one-rep max per exercise.",
        DateRange,
        get_strength,
    ),
    Tool(
        "get_weekly_summary",
        "Activities, distance, hours and climbing per sport group per week.",
        DateRange,
        get_weekly_summary,
    ),
    Tool(
        "get_wellness",
        f"Daily sleep, HRV, resting HR, readiness, body battery, stress, training status and "
        f"VO2max, plus HRV and resting HR against their 60-day normal range. At most "
        f"{MAX_WELLNESS_DAYS} days.",
        WellnessRange,
        get_wellness,
    ),
    Tool(
        "list_activities",
        "Activities in a date range, newest first, with id, type, distance, time, climbing, "
        "average HR, load and terrain.",
        ActivityQuery,
        list_activities,
    ),
    Tool(
        "save_note",
        "Save a short fact to remember in later conversations, for example an injury, a "
        "preference or a schedule change. Write it so it makes sense on its own.",
        NewNote,
        save_note,
    ),
)
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: (
                {name: strip_titles(value) for name, value in child.items()}
                if key == "properties"
                else strip_titles(child)
            )
            for key, child in node.items()
            if key != "title"
        }
    if isinstance(node, list):
        return [strip_titles(item) for item in node]
    return node


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": strip_titles(tool.input_model.model_json_schema()),
            "eager_input_streaming": True,
        }
        for tool in sorted(TOOLS, key=lambda t: t.name)
    ]


def run_tool(ctx: ToolContext, name: str, raw_input: Any) -> tuple[str, bool]:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return f"Unknown tool {name}", False
    try:
        args = tool.input_model.model_validate(raw_input)
    except ValidationError as error:
        return f"Invalid input: {error}", False
    try:
        return tool.handler(ctx, args), True
    except LookupError as error:
        return str(error), False
    except Exception:
        log.exception("Tool %s failed", name)
        return f"{name} failed with an internal error", False
