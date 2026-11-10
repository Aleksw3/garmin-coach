import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from garmin_coach.api.profile import ProfileDep, SessionDep
from garmin_coach.api.routes import activity_out
from garmin_coach.api.schemas import ActivityOut
from garmin_coach.coach.plan import (
    Change,
    NewSeason,
    PlanError,
    SeasonWeekSpec,
    SessionSpec,
    accept_proposal,
    pending_proposals,
    proposal_body,
    reject_proposal,
    sessions_between,
)
from garmin_coach.garmin.source import (
    GarminAuthError,
    GarminError,
    GarminRateLimited,
    GarminSource,
)
from garmin_coach.garmin.workouts import (
    WorkoutError,
    forget_workout,
    remove_from_watch,
    send_to_watch,
)
from garmin_coach.metrics.compliance import match_sessions
from garmin_coach.metrics.season import season_progress
from garmin_coach.metrics.zones import current_zones
from garmin_coach.models import Activity, Plan, PlannedSession, PlanProposal, SessionMatch
from garmin_coach.normalize.sports import sport_groups

log = logging.getLogger(__name__)

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
    sent_to_watch_at: datetime | None = None
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
    season: NewSeason | None


class SeasonWeekOut(SeasonWeekSpec):
    done_hours: float
    done_climb_m: float
    done_longest_h: float


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
        season=body.season,
    )


@router.get("/season", response_model=list[SeasonWeekOut])
def get_season(session: SessionDep, start: date, end: date) -> list[SeasonWeekOut]:
    return [
        SeasonWeekOut(
            week_start=entry.week.week_start,
            phase=entry.week.phase,  # type: ignore[arg-type]
            hours=entry.week.hours,
            climb_m=entry.week.climb_m,
            longest_h=entry.week.longest_h,
            focus=entry.week.focus,
            done_hours=entry.done.hours,
            done_climb_m=entry.done.climb_m,
            done_longest_h=entry.done.longest_h,
        )
        for entry in season_progress(session, start, end)
    ]


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


def sessions_on_watch(session: SessionDep) -> dict[int, tuple[int, int | None]]:
    rows = session.execute(
        select(
            PlannedSession.id, PlannedSession.garmin_workout_id, PlannedSession.garmin_schedule_id
        ).where(PlannedSession.garmin_workout_id.is_not(None))
    )
    return {row.id: (row.garmin_workout_id, row.garmin_schedule_id) for row in rows}


def follow_plan_on_watch(
    source: GarminSource,
    session: SessionDep,
    on_watch: dict[int, tuple[int, int | None]],
    updated: set[int],
) -> None:
    zones = current_zones(session)
    for session_id, (workout_id, schedule_id) in on_watch.items():
        row = session.get(PlannedSession, session_id)
        try:
            if row is None:
                forget_workout(source, workout_id, schedule_id)
            elif session_id in updated:
                try:
                    send_to_watch(source, row, zones, datetime.now())
                except WorkoutError:
                    remove_from_watch(source, row)
        except GarminError:
            log.exception("Could not update planned session %s on the watch", session_id)
        session.commit()


@router.post("/proposals/{proposal_id}/accept", response_model=ProposalOut)
def accept(session: SessionDep, profile: ProfileDep, proposal_id: int) -> ProposalOut:
    proposal = find_proposal(session, proposal_id)
    on_watch = sessions_on_watch(session)
    updated = {
        c.session_id
        for c in proposal_body(proposal).changes
        if c.op == "update" and c.session_id is not None
    }
    try:
        first, last = accept_proposal(session, proposal, datetime.now())
    except PlanError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    match_sessions(session, first, last)
    session.commit()
    if on_watch:
        follow_plan_on_watch(profile.garmin(), session, on_watch, updated)
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


@contextmanager
def garmin_errors() -> Iterator[None]:
    try:
        yield
    except WorkoutError as error:
        raise HTTPException(422, str(error)) from error
    except GarminAuthError as error:
        raise HTTPException(
            409, "Garmin login failed. Log in again on the Settings page."
        ) from error
    except GarminRateLimited as error:
        raise HTTPException(429, "Garmin is limiting requests. Try again in a while.") from error
    except GarminError as error:
        raise HTTPException(502, f"Garmin did not accept the workout: {error}") from error


@router.post("/sessions/{session_id}/watch", response_model=SessionOut)
def send_session_to_watch(session: SessionDep, profile: ProfileDep, session_id: int) -> SessionOut:
    row = find_session(session, session_id)
    with garmin_errors():
        send_to_watch(profile.garmin(), row, current_zones(session), datetime.now())
    session.commit()
    return session_out(session, row)


@router.delete("/sessions/{session_id}/watch", response_model=SessionOut)
def remove_session_from_watch(
    session: SessionDep, profile: ProfileDep, session_id: int
) -> SessionOut:
    row = find_session(session, session_id)
    if row.garmin_workout_id is not None:
        with garmin_errors():
            remove_from_watch(profile.garmin(), row)
        session.commit()
    return session_out(session, row)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session: SessionDep, profile: ProfileDep, session_id: int) -> Response:
    row = find_session(session, session_id)
    if row.garmin_workout_id is not None:
        with garmin_errors():
            remove_from_watch(profile.garmin(), row)
    day = row.day
    session.delete(row)
    session.flush()
    match_sessions(session, day, day)
    session.commit()
    return Response(status_code=204)
