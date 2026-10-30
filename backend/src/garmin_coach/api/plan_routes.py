import json
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from garmin_coach.api.routes import SessionDep, activity_out
from garmin_coach.api.schemas import ActivityOut
from garmin_coach.coach.plan import (
    Change,
    PlanError,
    SessionSpec,
    accept_proposal,
    pending_proposals,
    proposal_body,
    reject_proposal,
    sessions_between,
)
from garmin_coach.metrics.compliance import match_sessions
from garmin_coach.models import Activity, Plan, PlannedSession, PlanProposal, SessionMatch
from garmin_coach.normalize.sports import sport_groups

router = APIRouter(prefix="/api")

MAX_CALENDAR_DAYS = 200


class MatchOut(BaseModel):
    activity_id: int
    compliance: float | None
    details: dict[str, list[float]]


class SessionOut(SessionSpec):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: int
    plan_id: int
    skipped: bool
    match: MatchOut | None = None


def session_out(session: SessionDep, row: PlannedSession) -> SessionOut:
    match = session.get(SessionMatch, row.id)
    out = SessionOut.model_validate(row)
    if match is not None:
        out.match = MatchOut(
            activity_id=match.activity_id,
            compliance=match.compliance,
            details=json.loads(match.details),
        )
    return out


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int | None
    title: str
    description: str | None
    start_date: date
    end_date: date


class CalendarOut(BaseModel):
    start: date
    end: date
    plans: list[PlanOut]
    sessions: list[SessionOut]
    activities: list[ActivityOut]


class NewPlanOut(BaseModel):
    title: str
    goal_id: int | None
    description: str | None
    sessions: list[SessionSpec]


class ChangeOut(Change):
    current: SessionOut | None


class ProposalOut(BaseModel):
    id: int
    created_at: datetime
    conversation_id: int | None
    summary: str
    reason: str
    status: str
    plan: NewPlanOut | None
    changes: list[ChangeOut]


class SessionPatch(BaseModel):
    skipped: bool


def proposal_out(session: SessionDep, proposal: PlanProposal) -> ProposalOut:
    body = proposal_body(proposal)
    changes = []
    for change in body.changes:
        current = session.get(PlannedSession, change.session_id) if change.session_id else None
        changes.append(
            ChangeOut(
                **change.model_dump(),
                current=session_out(session, current) if current else None,
            )
        )
    return ProposalOut(
        id=proposal.id,
        created_at=proposal.created_at,
        conversation_id=proposal.conversation_id,
        summary=proposal.summary,
        reason=proposal.reason,
        status=proposal.status,
        plan=NewPlanOut(**body.plan.model_dump()) if body.plan else None,
        changes=changes,
    )


@router.get("/plan", response_model=CalendarOut)
def get_calendar(session: SessionDep, start: date, end: date) -> CalendarOut:
    if start > end or (end - start).days > MAX_CALENDAR_DAYS:
        raise HTTPException(422, f"Pick a range of at most {MAX_CALENDAR_DAYS} days")
    groups = sport_groups(session)
    plans = session.scalars(
        select(Plan).where(Plan.start_date <= end, Plan.end_date >= start).order_by(Plan.start_date)
    )
    activities = session.scalars(
        select(Activity)
        .where(Activity.local_date >= start, Activity.local_date <= end)
        .order_by(Activity.start_time_local)
    )
    return CalendarOut(
        start=start,
        end=end,
        plans=[PlanOut.model_validate(plan) for plan in plans],
        sessions=[session_out(session, row) for row in sessions_between(session, start, end)],
        activities=[activity_out(activity, groups) for activity in activities],
    )


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    session: SessionDep, status: Annotated[str, Query(pattern="^(pending|all)$")] = "pending"
) -> list[ProposalOut]:
    if status == "pending":
        proposals = pending_proposals(session)
    else:
        since = datetime.now() - timedelta(days=60)
        proposals = list(
            session.scalars(
                select(PlanProposal)
                .where(PlanProposal.created_at >= since)
                .order_by(PlanProposal.created_at.desc())
            )
        )
    return [proposal_out(session, proposal) for proposal in proposals]


def find_proposal(session: SessionDep, proposal_id: int) -> PlanProposal:
    proposal = session.get(PlanProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    return proposal


@router.post("/proposals/{proposal_id}/accept", response_model=ProposalOut)
def accept(session: SessionDep, proposal_id: int) -> ProposalOut:
    proposal = find_proposal(session, proposal_id)
    try:
        first, last = accept_proposal(session, proposal, datetime.now())
    except PlanError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    match_sessions(session, first, last)
    session.commit()
    return proposal_out(session, proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject(session: SessionDep, proposal_id: int) -> ProposalOut:
    proposal = find_proposal(session, proposal_id)
    try:
        reject_proposal(proposal, datetime.now())
    except PlanError as error:
        raise HTTPException(409, str(error)) from error
    session.commit()
    return proposal_out(session, proposal)


def find_session(session: SessionDep, session_id: int) -> PlannedSession:
    row = session.get(PlannedSession, session_id)
    if row is None:
        raise HTTPException(404, "Planned session not found")
    return row


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def patch_session(session: SessionDep, session_id: int, body: SessionPatch) -> SessionOut:
    row = find_session(session, session_id)
    row.skipped = body.skipped
    match_sessions(session, row.day, row.day)
    session.commit()
    return session_out(session, row)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session: SessionDep, session_id: int) -> Response:
    row = find_session(session, session_id)
    day = row.day
    session.delete(row)
    session.flush()
    match_sessions(session, day, day)
    session.commit()
    return Response(status_code=204)
