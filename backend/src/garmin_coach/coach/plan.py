from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from garmin_coach.models import Goal, Plan, PlannedSession, PlanProposal, SeasonWeek

MAX_SESSIONS = 150
MAX_PLAN_DAYS = 120
MAX_SEASON_WEEKS = 60

Sport = Literal["run", "vertical", "ski", "cycling", "strength", "other", "rest"]
Phase = Literal["base", "build", "peak", "taper", "race", "recovery"]
Kind = Literal[
    "easy", "long", "hills", "intervals", "tempo", "race", "strength", "mobility", "cross", "rest"
]


class PlanError(ValueError):
    pass


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["warmup", "steady", "intervals", "cooldown"]
    duration_min: float | None = Field(
        default=None, gt=0, le=600, description="For intervals, the length of one repeat"
    )
    distance_km: float | None = Field(
        default=None, gt=0, le=100, description="For intervals, the length of one repeat"
    )
    repeats: int | None = Field(default=None, ge=1, le=50, description="Only for intervals")
    grade_pct: float | None = Field(
        default=None, ge=1, le=40, description="For hill repeats, the gradient in percent"
    )
    target: str | None = Field(
        default=None, max_length=100, description="HR zone or effort, for example Z2 or Z3"
    )
    recovery: str | None = Field(
        default=None, max_length=100, description="Between repeats, for example 2 min jog down"
    )
    note: str | None = Field(default=None, max_length=300)


class WarmupSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reps: int = Field(ge=1, le=30)
    weight_kg: float = Field(ge=0, le=500)


class Exercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    sets: int = Field(ge=1, le=20)
    reps: str = Field(min_length=1, max_length=40, description="For example 8, 8/leg or 20 s/side")
    load: str | None = Field(
        default=None, max_length=60, description="For example 60 kg, bodyweight or 2x10 kg"
    )
    rest_s: int | None = Field(default=None, ge=0, le=600, description="Rest between sets")
    warmup_sets: list[WarmupSet] = Field(
        default=[],
        max_length=4,
        description="Lighter sets that ramp up to the working load, before the working sets",
    )
    note: str | None = Field(default=None, max_length=200)


class SessionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date = Field(description="YYYY-MM-DD")
    sport: Sport
    kind: Kind
    title: str = Field(
        min_length=1, max_length=200, description="Short name, for example Hill repeats"
    )
    duration_min: float | None = Field(default=None, gt=0, le=900)
    distance_km: float | None = Field(default=None, gt=0, le=200)
    elevation_gain_m: float | None = Field(default=None, ge=0, le=10000)
    intensity: str | None = Field(
        default=None, max_length=200, description="HR zone or effort, for example Z2 or 6x3 min Z4"
    )
    steps: list[Step] = Field(
        default=[],
        max_length=12,
        description="The parts of a run, ride, hike or ski session in order. Empty for strength",
    )
    exercises: list[Exercise] = Field(
        default=[], max_length=20, description="Strength and mobility exercises in order"
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Short notes the steps and exercises don't cover, such as terrain or fueling",
    )


class NewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    goal_id: int | None = None
    description: str | None = Field(
        default=None, max_length=4000, description="The block's purpose, structure and progression"
    )
    sessions: list[SessionSpec] = Field(min_length=1, max_length=MAX_SESSIONS)

    @model_validator(mode="after")
    def check_span(self) -> Self:
        days = [s.day for s in self.sessions]
        if (max(days) - min(days)).days > MAX_PLAN_DAYS:
            raise ValueError(f"a plan covers at most {MAX_PLAN_DAYS} days")
        return self


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["add", "update", "remove"]
    session_id: int | None = Field(default=None, description="Required for update and remove")
    session: SessionSpec | None = Field(
        default=None, description="Required for add and update. Update replaces every field"
    )

    @model_validator(mode="after")
    def check_fields(self) -> Self:
        if self.op in ("update", "remove") and self.session_id is None:
            raise ValueError(f"{self.op} needs session_id")
        if self.op in ("add", "update") and self.session is None:
            raise ValueError(f"{self.op} needs session")
        return self


class SeasonWeekSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date = Field(description="The Monday of the week, YYYY-MM-DD")
    phase: Phase
    hours: float = Field(ge=0, le=60, description="Training hours without bike commutes")
    climb_m: float | None = Field(
        default=None, ge=0, le=30000, description="Climbing on foot, running and hiking"
    )
    longest_h: float | None = Field(
        default=None, ge=0, le=40, description="Longest single run or hike in hours"
    )
    focus: str | None = Field(
        default=None, max_length=300, description="What the week is for, in one sentence"
    )

    @model_validator(mode="after")
    def check_monday(self) -> Self:
        if self.week_start.weekday() != 0:
            raise ValueError(f"{self.week_start} is not a Monday")
        return self


class NewSeason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: int | None = None
    weeks: list[SeasonWeekSpec] = Field(min_length=1, max_length=MAX_SEASON_WEEKS)

    @model_validator(mode="after")
    def check_weeks(self) -> Self:
        starts = [week.week_start for week in self.weeks]
        if len(set(starts)) != len(starts):
            raise ValueError("a week appears twice")
        return self


class ProposalBody(BaseModel):
    plan: NewPlan | None = None
    changes: list[Change] = []
    season: NewSeason | None = None


def session_row(plan_id: int, spec: SessionSpec) -> PlannedSession:
    return PlannedSession(plan_id=plan_id, **spec.model_dump())


def check_ids(session: Session, body: ProposalBody) -> None:
    ids = {c.session_id for c in body.changes if c.session_id is not None}
    found = set(session.scalars(select(PlannedSession.id).where(PlannedSession.id.in_(ids))))
    missing = ids - found
    if missing:
        raise PlanError(f"No planned session with id {', '.join(map(str, sorted(missing)))}")
    goal_ids = [body.plan.goal_id if body.plan else None]
    goal_ids.append(body.season.goal_id if body.season else None)
    for goal_id in goal_ids:
        if goal_id is not None and session.get(Goal, goal_id) is None:
            raise PlanError(f"No goal with id {goal_id}")


def create_proposal(
    session: Session,
    summary: str,
    reason: str,
    body: ProposalBody,
    conversation_id: int | None,
    now: datetime,
) -> PlanProposal:
    if body.plan is None and not body.changes and body.season is None:
        raise PlanError("The proposal has no plan, no changes and no season outline")
    check_ids(session, body)
    proposal = PlanProposal(
        created_at=now,
        conversation_id=conversation_id,
        summary=summary,
        reason=reason,
        body=body.model_dump_json(exclude_none=True),
        status="pending",
    )
    session.add(proposal)
    session.flush()
    return proposal


def proposal_body(proposal: PlanProposal) -> ProposalBody:
    return ProposalBody.model_validate_json(proposal.body)


def plan_for_day(session: Session, day: date, now: datetime) -> Plan:
    plan = session.scalars(
        select(Plan)
        .where(Plan.start_date <= day, Plan.end_date >= day)
        .order_by(Plan.created_at.desc())
        .limit(1)
    ).first()
    if plan is None:
        plan = session.scalars(select(Plan).order_by(Plan.created_at.desc()).limit(1)).first()
    if plan is None:
        plan = Plan(title="Single sessions", start_date=day, end_date=day, created_at=now)
        session.add(plan)
        session.flush()
    plan.start_date = min(plan.start_date, day)
    plan.end_date = max(plan.end_date, day)
    return plan


def affected_days(session: Session, body: ProposalBody) -> tuple[date, date] | None:
    days = [s.day for s in body.plan.sessions] if body.plan else []
    days += [c.session.day for c in body.changes if c.session]
    days += [week.week_start for week in body.season.weeks] if body.season else []
    ids = [c.session_id for c in body.changes if c.session_id is not None]
    days += list(session.scalars(select(PlannedSession.day).where(PlannedSession.id.in_(ids))))
    return (min(days), max(days)) if days else None


def accept_proposal(session: Session, proposal: PlanProposal, now: datetime) -> tuple[date, date]:
    if proposal.status != "pending":
        raise PlanError(f"The proposal is already {proposal.status}")
    body = proposal_body(proposal)
    check_ids(session, body)
    span = affected_days(session, body)
    if body.plan:
        first = min(s.day for s in body.plan.sessions)
        session.execute(delete(PlannedSession).where(PlannedSession.day >= first))
        plan = Plan(
            goal_id=body.plan.goal_id,
            title=body.plan.title,
            description=body.plan.description,
            start_date=first,
            end_date=max(s.day for s in body.plan.sessions),
            created_at=now,
        )
        session.add(plan)
        session.flush()
        session.add_all(session_row(plan.id, spec) for spec in body.plan.sessions)
    if body.season:
        first_week = min(week.week_start for week in body.season.weeks)
        session.execute(delete(SeasonWeek).where(SeasonWeek.week_start >= first_week))
        session.add_all(
            SeasonWeek(goal_id=body.season.goal_id, **week.model_dump())
            for week in body.season.weeks
        )
    for change in body.changes:
        if change.op == "add" and change.session:
            plan = plan_for_day(session, change.session.day, now)
            session.add(session_row(plan.id, change.session))
            continue
        row = session.get(PlannedSession, change.session_id)
        if row is None:
            raise PlanError(f"No planned session with id {change.session_id}")
        if change.op == "remove":
            session.delete(row)
        elif change.session:
            for field, value in change.session.model_dump().items():
                setattr(row, field, value)
            owner = session.get(Plan, row.plan_id)
            if owner is not None:
                owner.start_date = min(owner.start_date, row.day)
                owner.end_date = max(owner.end_date, row.day)
    proposal.status = "accepted"
    proposal.decided_at = now
    session.flush()
    assert span is not None
    return span


def reject_proposal(proposal: PlanProposal, now: datetime) -> None:
    if proposal.status != "pending":
        raise PlanError(f"The proposal is already {proposal.status}")
    proposal.status = "rejected"
    proposal.decided_at = now


def session_targets(row: PlannedSession | SessionSpec) -> str:
    parts = []
    if row.duration_min:
        parts.append(f"{row.duration_min:.0f} min")
    if row.distance_km:
        parts.append(f"{row.distance_km:g} km")
    if row.elevation_gain_m:
        parts.append(f"{row.elevation_gain_m:.0f} m up")
    if row.intensity:
        parts.append(row.intensity)
    return ", ".join(parts)


def amount(duration_min: float | None, distance_km: float | None) -> str:
    parts = []
    if duration_min:
        parts.append(f"{duration_min:g} min")
    if distance_km:
        parts.append(f"{distance_km:g} km")
    return " or ".join(parts)


def step_text(step: Step) -> str:
    size = amount(step.duration_min, step.distance_km)
    if step.repeats:
        size = f"{step.repeats}x {size}".strip()
    parts = [step.kind, size, step.target]
    if step.grade_pct:
        parts.append(f"at {step.grade_pct:g}% gradient")
    if step.recovery:
        parts.append(f"recovery {step.recovery}")
    parts.append(step.note)
    return " ".join(part for part in parts if part)


def exercise_text(exercise: Exercise) -> str:
    text = f"{exercise.name} {exercise.sets}x{exercise.reps}"
    if exercise.load:
        text += f" @ {exercise.load}"
    if exercise.rest_s:
        text += f", rest {exercise.rest_s} s"
    if exercise.warmup_sets:
        ramp = ", ".join(f"{w.weight_kg:g} kg x{w.reps}" for w in exercise.warmup_sets)
        text += f", warm-up sets {ramp}"
    if exercise.note:
        text += f" ({exercise.note})"
    return text


def session_structure(row: PlannedSession | SessionSpec) -> str | None:
    steps = [step_text(Step.model_validate(step)) for step in row.steps or []]
    exercises = [exercise_text(Exercise.model_validate(e)) for e in row.exercises or []]
    parts = []
    if steps:
        parts.append("steps: " + "; ".join(steps))
    if exercises:
        parts.append("exercises: " + "; ".join(exercises))
    return " | ".join(parts) or None


def sessions_between(session: Session, first: date, last: date) -> list[PlannedSession]:
    return list(
        session.scalars(
            select(PlannedSession)
            .where(PlannedSession.day >= first, PlannedSession.day <= last)
            .order_by(PlannedSession.day, PlannedSession.id)
        )
    )


def pending_proposals(session: Session) -> list[PlanProposal]:
    return list(
        session.scalars(
            select(PlanProposal)
            .where(PlanProposal.status == "pending")
            .order_by(PlanProposal.created_at)
        )
    )
