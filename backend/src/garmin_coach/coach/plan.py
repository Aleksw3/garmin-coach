from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from garmin_coach.models import Goal, Plan, PlannedSession, PlanProposal

MAX_SESSIONS = 150
MAX_PLAN_DAYS = 120

Sport = Literal["run", "vertical", "ski", "cycling", "strength", "other", "rest"]
Kind = Literal[
    "easy", "long", "hills", "intervals", "tempo", "race", "strength", "mobility", "cross", "rest"
]


class PlanError(ValueError):
    pass


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
    description: str | None = Field(
        default=None, max_length=2000, description="How to do it, and exercises for strength"
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


class ProposalBody(BaseModel):
    plan: NewPlan | None = None
    changes: list[Change] = []


def session_row(plan_id: int, spec: SessionSpec) -> PlannedSession:
    return PlannedSession(plan_id=plan_id, **spec.model_dump())


def check_ids(session: Session, body: ProposalBody) -> None:
    ids = {c.session_id for c in body.changes if c.session_id is not None}
    found = set(session.scalars(select(PlannedSession.id).where(PlannedSession.id.in_(ids))))
    missing = ids - found
    if missing:
        raise PlanError(f"No planned session with id {', '.join(map(str, sorted(missing)))}")
    if body.plan and body.plan.goal_id is not None and session.get(Goal, body.plan.goal_id) is None:
        raise PlanError(f"No goal with id {body.plan.goal_id}")


def create_proposal(
    session: Session,
    summary: str,
    reason: str,
    body: ProposalBody,
    conversation_id: int | None,
    now: datetime,
) -> PlanProposal:
    if body.plan is None and not body.changes:
        raise PlanError("The proposal has no plan and no changes")
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
