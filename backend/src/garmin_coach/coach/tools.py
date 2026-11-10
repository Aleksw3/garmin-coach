import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from garmin_coach.coach.plan import (
    Change,
    NewPlan,
    NewSeason,
    PlanError,
    ProposalBody,
    create_proposal,
    pending_proposals,
    session_structure,
    session_targets,
    sessions_between,
)
from garmin_coach.course import course_text, describe, goal_course
from garmin_coach.evidence.library import citation, search
from garmin_coach.garmin.workouts import find_exercises
from garmin_coach.metrics.hills import find_hills
from garmin_coach.metrics.load import training_load
from garmin_coach.metrics.projection import project, projection_text
from garmin_coach.metrics.rating import rating_text
from garmin_coach.metrics.recovery import hrv_baseline, resting_hr_baseline
from garmin_coach.metrics.running import climb_per_km, terrain
from garmin_coach.metrics.season import season_progress, week_targets
from garmin_coach.metrics.strength import effective_sets
from garmin_coach.metrics.summary import running_lines, strength_lines
from garmin_coach.metrics.zones import (
    activity_zone_seconds,
    current_zones,
    weekly_zone_seconds,
    zones_line,
)
from garmin_coach.models import (
    Activity,
    ActivityLap,
    ActivityRating,
    ActivityZoneTime,
    AthleteProfile,
    CoachNote,
    DailyWellness,
    Evidence,
    Goal,
    GoalCourse,
    Plan,
    PlannedSession,
    SessionMatch,
)
from garmin_coach.normalize.sports import OTHER, sport_groups
from garmin_coach.reports import format_weekly_totals, week_start, weekly_totals
from garmin_coach.sync import LAST_SYNC, get_state

log = logging.getLogger(__name__)

MAX_RANGE_DAYS = 731
MAX_WELLNESS_DAYS = 92
MAX_ACTIVITIES = 150
RUNNING_GROUPS = ("run", "vertical")
MAX_LAPS = 40
MAX_NOTES = 50
MAX_EXERCISES = 40
TERRAIN_GROUPS = ("run", "vertical")


@dataclass
class ToolContext:
    session: Session
    now: datetime
    trimp_coefficient: float
    conversation_id: int | None = None
    research: Session | None = None

    @property
    def library(self) -> Session:
        return self.research or self.session

    @property
    def today(self) -> date:
        return self.now.date()


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


class GoalId(ToolInput):
    goal_id: int | None = Field(
        default=None, description="Leave empty for the main active race goal"
    )


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


class ExerciseQuery(ToolInput):
    term: str = Field(
        min_length=2, max_length=100, description="Part of a name, for example split squat"
    )


class EvidenceQuery(ToolInput):
    query: str = Field(
        min_length=2,
        max_length=300,
        description="Plain words, for example strength training runners",
    )


class HillQuery(ToolInput):
    rep_minutes: float | None = Field(
        default=None, gt=0, le=30, description="Length of one repeat in minutes"
    )
    rep_meters: float | None = Field(
        default=None, gt=0, le=5000, description="Or the length of one repeat in meters"
    )
    grade_pct: float = Field(default=8, ge=2, le=40, description="Target gradient in percent")
    tolerance_pct: float = Field(
        default=2, ge=0.5, le=10, description="How far the gradient may be from the target"
    )
    near: str | None = Field(
        default=None,
        max_length=100,
        description="Place name from the activities, for example Oppdal. Leave empty for home",
    )
    max_km: float = Field(default=10, gt=0, le=100, description="Search radius in km")

    @model_validator(mode="after")
    def check_length(self) -> Self:
        if (self.rep_minutes is None) == (self.rep_meters is None):
            raise ValueError("give either rep_minutes or rep_meters")
        return self


class ProposalText(ToolInput):
    summary: str = Field(
        min_length=1, max_length=300, description="One line the athlete sees on the Plan page"
    )
    reason: str = Field(
        min_length=1, max_length=3000, description="Why, with the numbers it is based on"
    )


class PlanProposalInput(ProposalText):
    plan: NewPlan


class SeasonInput(ProposalText):
    season: NewSeason


class ChangesInput(ProposalText):
    changes: list[Change] = Field(min_length=1, max_length=60)


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


def activity_line(
    activity: Activity, groups: dict[str, str], rating: ActivityRating | None = None
) -> str:
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
            f"felt {rating.effort}/10" if rating and rating.effort is not None else None,
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
    shown = activities[:MAX_ACTIVITIES]
    ratings = {
        rating.activity_id: rating
        for rating in ctx.session.scalars(
            select(ActivityRating).where(ActivityRating.activity_id.in_([a.id for a in shown]))
        )
    }
    lines = [activity_line(a, groups, ratings.get(a.id)) for a in shown]
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
    felt = rating_text(ctx.session.get(ActivityRating, activity.id))
    lines.append(
        f"The athlete's own rating: {felt}"
        if felt
        else "The athlete has not rated how this session felt"
    )
    zones = ctx.session.scalars(
        select(ActivityZoneTime)
        .where(ActivityZoneTime.activity_id == activity.id)
        .order_by(ActivityZoneTime.kind, ActivityZoneTime.zone)
    ).all()
    own = current_zones(ctx.session)
    own_seconds = activity_zone_seconds(ctx.session, activity.id, own) if own else []
    if sum(own_seconds) > 0:
        lines.append(
            "Time in the athlete's HR zones: "
            + ", ".join(f"Z{n} {hours_minutes(t)}" for n, t in enumerate(own_seconds, 1))
        )
    for kind in ("power",) if sum(own_seconds) > 0 else ("hr", "power"):
        kind_zones = [z for z in zones if z.kind == kind]
        if kind_zones:
            lines.append(
                f"Time in Garmin {kind} zones: "
                + ", ".join(f"Z{z.zone} {hours_minutes(z.seconds)}" for z in kind_zones)
            )
    if activity.hr_drift_pct is not None:
        decoupling = (
            ""
            if activity.decoupling_pct is None
            else f", pace to HR decoupling {activity.decoupling_pct:.1f}%"
        )
        lines.append(
            f"After a 15 min warm-up, HR went from {activity.drift_first_hr:.0f} in the first half "
            f"to {activity.drift_second_hr:.0f} in the second: drift {activity.hr_drift_pct:.1f}%"
            f"{decoupling}. Only meaningful for steady efforts"
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
                        f"lap {lap.lap_index}",
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


def get_zone_time(ctx: ToolContext, args: DateRange) -> str:
    zones = current_zones(ctx.session)
    if zones is None:
        return "No HR zones set. The athlete can add LT1 and LT2 on the Trends page"
    first, last = week_start(args.start), args.end
    groups = sport_groups(ctx.session)
    activities = ctx.session.scalars(
        select(Activity).where(Activity.local_date >= first, Activity.local_date <= last)
    ).all()
    lines = [zones_line(ctx.session) or ""]
    for label, ids in (
        (
            "Running and hiking",
            [a.id for a in activities if activity_group(a, groups) in RUNNING_GROUPS],
        ),
        ("All training except commutes", [a.id for a in activities if not a.is_commute]),
    ):
        lines.append(f"{label}, minutes per zone Z1 to Z5:")
        for week, seconds in sorted(
            weekly_zone_seconds(ctx.session, first, last, ids, zones).items()
        ):
            minutes = " / ".join(f"{total / 60:.0f}" for total in seconds)
            lines.append(f"  week from {week}: {minutes}")
    return "\n".join(lines)


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
    lines.append(zones_line(ctx.session) or "HR zones: not set")
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
    with_course = set(ctx.session.scalars(select(GoalCourse.goal_id)))
    return (
        "\n".join(
            goal_text(g) + (" | course uploaded, see get_course" if g.id in with_course else "")
            for g in goals
        )
        or "No goals set"
    )


def get_race_projection(ctx: ToolContext, args: GoalId) -> str:
    goal = (
        ctx.session.get(Goal, args.goal_id)
        if args.goal_id is not None
        else ctx.session.scalars(
            select(Goal)
            .where(Goal.status == "active", Goal.kind == "race")
            .order_by(Goal.priority, Goal.target_date)
        ).first()
    )
    if goal is None:
        return "No such goal"
    projection = project(ctx.session, goal, ctx.today)
    if projection is None:
        return (
            f"No estimate for goal {goal.id} {goal.title}. It needs a course or a distance on "
            "the goal, and a run or hike of 60 minutes or more in the last 180 days"
        )
    return "\n".join([f"goal {goal.id} {goal.title}", *projection_text(projection)])


def get_course(ctx: ToolContext, args: GoalId) -> str:
    found = goal_course(ctx.session, args.goal_id)
    if found is None:
        return "No course uploaded. The athlete can upload a GPX file on the Goals page"
    goal, row = found
    return "\n".join([f"goal {goal.id} {goal.title}", *course_text(describe(row))])


def get_notes(ctx: ToolContext, args: NoteQuery) -> str:
    query = select(CoachNote).order_by(CoachNote.created_at.desc()).limit(MAX_NOTES)
    if args.query:
        query = query.where(CoachNote.text.icontains(args.query))
    notes = ctx.session.scalars(query).all()
    return "\n".join(f"{n.created_at:%Y-%m-%d}: {n.text}" for n in notes) or "No notes"


def plan_lines(ctx: ToolContext, args: DateRange) -> list[str]:
    plans = ctx.session.scalars(
        select(Plan)
        .where(Plan.start_date <= args.end, Plan.end_date >= args.start)
        .order_by(Plan.start_date)
    ).all()
    lines = [
        f"Plan {plan.id}: {plan.title} ({plan.start_date} to {plan.end_date})"
        + (f". {plan.description}" if plan.description else "")
        for plan in plans
    ]
    rows = sessions_between(ctx.session, args.start, args.end)
    lines.append(f"{len(rows)} planned sessions from {args.start} to {args.end}")
    matches = {
        m.planned_session_id: m
        for m in ctx.session.scalars(
            select(SessionMatch).where(SessionMatch.planned_session_id.in_([r.id for r in rows]))
        )
    }
    for row in rows:
        lines.append(
            joined(
                [
                    f"session {row.id}",
                    f"{row.day} {row.day:%a}",
                    f"{row.sport} {row.kind}",
                    row.title,
                    session_targets(row),
                    session_status(row, matches.get(row.id), ctx.today),
                    session_structure(row),
                    row.description,
                ]
            )
        )
    this_week = season_progress(ctx.session, args.start, args.end)
    for entry in this_week:
        lines.append(
            f"Season outline, week from {entry.week.week_start}: {entry.week.phase}, "
            f"targets {week_targets(entry.week)}"
        )
    for proposal in pending_proposals(ctx.session):
        lines.append(f"Pending proposal {proposal.id}, not accepted yet: {proposal.summary}")
    return lines


def session_status(row: PlannedSession, match: SessionMatch | None, today: date) -> str | None:
    if row.skipped:
        return "skipped"
    if match is not None:
        score = "" if match.compliance is None else f", compliance {match.compliance:.0f}%"
        return f"done as activity {match.activity_id}{score}"
    if row.sport != "rest" and row.day < today:
        return "not done"
    return None


def get_plan(ctx: ToolContext, args: DateRange) -> str:
    return "\n".join(plan_lines(ctx, args))


def propose_plan(ctx: ToolContext, args: PlanProposalInput) -> str:
    proposal = create_proposal(
        ctx.session,
        args.summary,
        args.reason,
        ProposalBody(plan=args.plan),
        ctx.conversation_id,
        ctx.now,
    )
    return (
        f"Created proposal {proposal.id} with {len(args.plan.sessions)} sessions. It replaces "
        f"planned sessions from {min(s.day for s in args.plan.sessions)} on once the athlete "
        "accepts it on the Plan page. Nothing changes before that."
    )


def propose_changes(ctx: ToolContext, args: ChangesInput) -> str:
    proposal = create_proposal(
        ctx.session,
        args.summary,
        args.reason,
        ProposalBody(changes=args.changes),
        ctx.conversation_id,
        ctx.now,
    )
    return (
        f"Created proposal {proposal.id} with {len(args.changes)} changes. The athlete accepts "
        "or rejects it on the Plan page. Nothing changes before that."
    )


def propose_season(ctx: ToolContext, args: SeasonInput) -> str:
    proposal = create_proposal(
        ctx.session,
        args.summary,
        args.reason,
        ProposalBody(season=args.season),
        ctx.conversation_id,
        ctx.now,
    )
    first = min(week.week_start for week in args.season.weeks)
    return (
        f"Created proposal {proposal.id} with {len(args.season.weeks)} weeks. It replaces the "
        f"season outline from the week of {first} on once the athlete accepts it on the Plan "
        "page. Nothing changes before that."
    )


def get_season(ctx: ToolContext, args: DateRange) -> str:
    progress = season_progress(ctx.session, args.start, args.end)
    if not progress:
        return "No season outline in this range. Propose one with propose_season"
    lines = ["Season outline per week: phase, targets, then what the athlete did"]
    for entry in progress:
        week, done = entry.week, entry.done
        line = f"  week from {week.week_start}: {week.phase}, targets {week_targets(week)}"
        if week.week_start <= ctx.today:
            line += (
                f" | done {done.hours:.1f} h, {done.climb_m:.0f} m climbing on foot, "
                f"longest {done.longest_h:.1f} h"
                + (" (week not over)" if week.week_start == week_start(ctx.today) else "")
            )
        lines.append(line + (f" | {week.focus}" if week.focus else ""))
    return "\n".join(lines)


def search_evidence(ctx: ToolContext, args: EvidenceQuery) -> str:
    entries = search(ctx.library, args.query)
    if not entries:
        return "No approved evidence matches this query"
    lines = []
    for entry in entries:
        disputed = ctx.library.get(Evidence, entry.disputed_by_id) if entry.disputed_by_id else None
        lines.append(
            "\n".join(
                line
                for line in [
                    f"evidence {entry.id} | {citation(entry)} | doi {entry.doi or 'none'} | "
                    f"grade {entry.grade} ({entry.design}"
                    + (f", n={entry.sample_size}" if entry.sample_size else "")
                    + ")",
                    f"  title: {entry.title}",
                    f"  claim: {entry.claim}",
                    f"  population: {entry.population}",
                    f"  takeaway: {entry.takeaway}",
                    f"  limitations: {entry.limitations}",
                    f"  disputed by evidence {disputed.id}: {citation(disputed)}, {disputed.claim}"
                    if disputed
                    else None,
                    f"  reviewer note: {entry.notes}" if entry.notes else None,
                ]
                if line
            )
        )
    return "\n".join(lines)


def find_garmin_exercises(ctx: ToolContext, args: ExerciseQuery) -> str:
    names = find_exercises(args.term)
    if not names:
        return "Garmin has no exercise with all these words. Try one word or a related movement"
    shown = names[:MAX_EXERCISES]
    more = (
        f"\n{len(names) - len(shown)} more, search with more words"
        if len(names) > len(shown)
        else ""
    )
    return "\n".join(shown) + more


def minutes_seconds(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def get_hills(ctx: ToolContext, args: HillQuery) -> str:
    result = find_hills(
        ctx.session,
        ctx.today,
        args.grade_pct,
        args.tolerance_pct,
        rep_minutes=args.rep_minutes,
        rep_meters=args.rep_meters,
        near=args.near,
        max_km=args.max_km,
    )
    if result.center is None:
        return f"No activities with GPS{f' at {args.near}' if args.near else ''}"
    place = args.near or "home (the most common start point of the last 180 days)"
    effort = result.effort
    lines = [
        f"Hills within {args.max_km:g} km of {place} with "
        f"{args.grade_pct - args.tolerance_pct:g} to {args.grade_pct + args.tolerance_pct:g}% "
        "gradient, found in the athlete's own GPS tracks, nearest first.",
        f"Repeat time assumes hard uphill effort at {pace(effort.flat_speed_mps)} "
        + (
            "flat-equivalent, the fastest 5% of the athlete's run climbs in the last year."
            if effort.from_data
            else "flat-equivalent, a default because there are too few run climbs."
        ),
    ]
    if not result.hills:
        lines.append("No hill fits. Try a wider gradient tolerance or a larger radius")
    for hill in result.hills:
        lines.append(
            joined(
                [
                    f"{hill.away_m / 1000:.1f} km away",
                    f"{hill.length_m:.0f} m at {100 * hill.grade:.1f}%, "
                    f"steepest 100 m {100 * hill.steepest_grade:.0f}%",
                    f"{hill.gain_m:.0f} m up",
                    f"about {minutes_seconds(hill.rep_seconds)} per repeat",
                    f"on {hill.visits} activities, last {hill.last_day}",
                    f"map {hill.map_url()}",
                ]
            )
        )
    return "\n".join(lines)


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
        "One activity in detail: pace, grade-adjusted pace, HR and power zones, laps, "
        "strength sets with reps and weight, and the athlete's own rating of the session.",
        ActivityId,
        get_activity,
    ),
    Tool(
        "find_garmin_exercises",
        "Search Garmin's strength exercise names. Planned exercises with an exact Garmin name "
        "show up by name on the athlete's watch and count toward the right muscle groups.",
        ExerciseQuery,
        find_garmin_exercises,
    ),
    Tool(
        "get_goals", "The athlete's goals, including race details and status.", ToolInput, get_goals
    ),
    Tool(
        "get_course",
        "The course of a goal race from the uploaded GPX track: distance, climbing and descent, "
        "the legs between aid stations or every 10 km, and the long climbs and descents.",
        GoalId,
        get_course,
    ),
    Tool(
        "get_race_projection",
        "A rough finish time estimate for a race goal from the athlete's recent long runs "
        "and hikes, with arrival times at each aid station or leg of an uploaded course. Use "
        "it for pacing and to check cutoffs.",
        GoalId,
        get_race_projection,
    ),
    Tool(
        "get_plan",
        "Planned sessions with their ids and targets, the plans they belong to, and proposals "
        "that are still waiting for the athlete.",
        DateRange,
        get_plan,
    ),
    Tool(
        "get_hills",
        "Hills for hill repeats from the athlete's own GPS tracks: sections that take about the "
        "given repeat time or length at the given gradient, with distance from home or a named "
        "place, steepest pitch, how often the athlete has been there and a map link.",
        HillQuery,
        get_hills,
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
        "get_zone_time",
        "Minutes per week in each of the athlete's HR zones, for running and hiking and for all "
        "training except commutes. Use it to check the intensity distribution.",
        DateRange,
        get_zone_time,
    ),
    Tool(
        "get_running_weeks",
        "Running and hiking per week: distance, time, climbing and descent, longest run, hours "
        "on flat, rolling and mountain terrain, and back-to-back long days.",
        DateRange,
        get_running_weeks,
    ),
    Tool(
        "get_season",
        "The season outline per week (phase and targets for hours, climbing on foot and the "
        "longest run or hike) next to what the athlete did in the weeks so far.",
        DateRange,
        get_season,
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
        "average HR, load, terrain and how hard the athlete said it felt.",
        ActivityQuery,
        list_activities,
    ),
    Tool(
        "propose_changes",
        "Propose adding, updating or removing single planned sessions, for example to move a "
        "long run or ease a week after poor recovery. Get session ids from get_plan first.",
        ChangesInput,
        propose_changes,
    ),
    Tool(
        "propose_plan",
        "Propose a training block of up to 120 days. When accepted it replaces every planned "
        "session from its first day on. Include rest days as sessions with sport rest.",
        PlanProposalInput,
        propose_plan,
    ),
    Tool(
        "propose_season",
        "Propose a season outline of up to 60 weeks: one row per week with a phase and targets "
        "for hours, climbing on foot and the longest run or hike. When accepted it replaces the "
        "outline from its first week on. It does not touch planned sessions.",
        SeasonInput,
        propose_season,
    ),
    Tool(
        "search_evidence",
        "Search the athlete's approved research library: claims, populations, takeaways, "
        "grades (A meta-analysis or systematic review, B randomized trial, C controlled or "
        "observational, D review or other) and DOIs.",
        EvidenceQuery,
        search_evidence,
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


def inline_refs(node: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            return inline_refs(definitions[node["$ref"].removeprefix("#/$defs/")], definitions)
        return {
            key: inline_refs(child, definitions) for key, child in node.items() if key != "$defs"
        }
    if isinstance(node, list):
        return [inline_refs(item, definitions) for item in node]
    return node


def input_schema(model: type[ToolInput]) -> dict[str, Any]:
    schema = model.model_json_schema()
    inlined: dict[str, Any] = strip_titles(inline_refs(schema, schema.get("$defs", {})))
    return inlined


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": input_schema(tool.input_model),
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
    except (LookupError, PlanError) as error:
        return str(error), False
    except Exception:
        log.exception("Tool %s failed", name)
        return f"{name} failed with an internal error", False
