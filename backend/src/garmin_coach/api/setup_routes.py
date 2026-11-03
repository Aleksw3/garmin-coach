import logging
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from garmin_coach.api.profile import ProfileDep, SessionDep
from garmin_coach.api.routes import ProfileSummaryOut
from garmin_coach.claude_settings import ClaudeSettings, InvalidApiKey, check_api_key
from garmin_coach.garmin.connect import GarminWebLogin, has_tokens
from garmin_coach.household import Household
from garmin_coach.jobs import ScheduledProfile, schedule_profile
from garmin_coach.models import Activity
from garmin_coach.sync import BACKFILL_CURSOR, LAST_SYNC, get_state

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def get_household(request: Request) -> Household:
    household: Household | None = request.app.state.household
    if household is None:
        raise HTTPException(503, "Setup from the app needs the server started with coach serve")
    return household


def get_garmin_login(request: Request) -> GarminWebLogin:
    login: GarminWebLogin = request.app.state.garmin_login
    return login


class ClaudeOut(BaseModel):
    available: bool
    key_set: bool
    key_hint: str | None
    source: Literal["app", "env"] | None
    monthly_budget_usd: float | None


class ClaudeIn(BaseModel):
    api_key: str | None = Field(default=None, min_length=20, max_length=300)
    monthly_budget_usd: float | None = Field(default=None, gt=0, le=1000)


def claude_out(claude: ClaudeSettings | None) -> ClaudeOut:
    if claude is None:
        return ClaudeOut(
            available=False, key_set=False, key_hint=None, source=None, monthly_budget_usd=None
        )
    return ClaudeOut(
        available=True,
        key_set=claude.api_key is not None,
        key_hint=claude.key_hint,
        source=claude.source,
        monthly_budget_usd=claude.monthly_budget_usd,
    )


@router.get("/claude", response_model=ClaudeOut)
def get_claude(request: Request) -> ClaudeOut:
    household: Household | None = request.app.state.household
    return claude_out(household.claude if household else None)


@router.put("/claude", response_model=ClaudeOut)
def set_claude(request: Request, body: ClaudeIn) -> ClaudeOut:
    household = get_household(request)
    api_key = body.api_key.strip() if body.api_key else None
    if api_key:
        try:
            check_api_key(api_key)
        except InvalidApiKey as error:
            raise HTTPException(400, str(error)) from error
    return claude_out(household.update_claude(api_key, body.monthly_budget_usd))


class NewProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    trimp_coefficient: float = Field(ge=1.0, le=3.0)


@router.post("/profiles", response_model=ProfileSummaryOut, status_code=201)
def add_profile(request: Request, body: NewProfileIn) -> ProfileSummaryOut:
    household = get_household(request)
    name = body.name.strip()
    runtime = household.add(name, body.trimp_coefficient)
    scheduler = request.app.state.scheduler
    if scheduler is not None:
        schedule_profile(
            scheduler,
            ScheduledProfile(runtime.slug, runtime.runner, runtime.proactive),
            len(household.profiles) - 1,
            request.app.state.schedule,
        )
    return ProfileSummaryOut(slug=runtime.slug, name=name)


class BackfillOut(BaseModel):
    days: int
    started_at: datetime


class GarminOut(BaseModel):
    connected: bool
    waiting_for_code: bool
    syncing: bool
    backfill: BackfillOut | None
    backfill_reached: date | None
    oldest_activity: date | None
    last_sync: str | None


def garmin_out(request: Request, profile: ProfileDep, session: SessionDep) -> GarminOut:
    household = get_household(request)
    backfill = profile.runner.backfill
    reached = get_state(session, BACKFILL_CURSOR)
    oldest = session.scalar(select(func.min(Activity.start_time_local)))
    return GarminOut(
        connected=has_tokens(household.settings.profile_tokens_dir(profile.slug)),
        waiting_for_code=profile.pending_login is not None,
        syncing=profile.runner.running,
        backfill=BackfillOut(days=backfill.days, started_at=backfill.started_at)
        if backfill
        else None,
        backfill_reached=date.fromisoformat(reached) if reached else None,
        oldest_activity=oldest.date() if oldest else None,
        last_sync=get_state(session, LAST_SYNC),
    )


@router.get("/garmin", response_model=GarminOut)
def get_garmin(request: Request, profile: ProfileDep, session: SessionDep) -> GarminOut:
    return garmin_out(request, profile, session)


class GarminLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class GarminCodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


def login_failed(error: Exception) -> HTTPException:
    log.warning("Garmin login from the app failed: %s", error)
    return HTTPException(400, f"Garmin login failed: {error}")


@router.post("/garmin/login", response_model=GarminOut)
def garmin_login(
    request: Request, profile: ProfileDep, session: SessionDep, body: GarminLoginIn
) -> GarminOut:
    tokens_dir = get_household(request).settings.profile_tokens_dir(profile.slug)
    profile.pending_login = None
    try:
        profile.pending_login = get_garmin_login(request).start(
            tokens_dir, body.email.strip(), body.password
        )
    except Exception as error:
        raise login_failed(error) from error
    return garmin_out(request, profile, session)


@router.post("/garmin/code", response_model=GarminOut)
def garmin_code(
    request: Request, profile: ProfileDep, session: SessionDep, body: GarminCodeIn
) -> GarminOut:
    tokens_dir = get_household(request).settings.profile_tokens_dir(profile.slug)
    pending = profile.pending_login
    if pending is None:
        raise HTTPException(409, "Log in with email and password first")
    try:
        get_garmin_login(request).finish(pending, body.code.strip(), tokens_dir)
    except Exception as error:
        raise login_failed(error) from error
    profile.pending_login = None
    return garmin_out(request, profile, session)


class BackfillIn(BaseModel):
    days: int = Field(ge=1, le=3650)


@router.post("/garmin/backfill", response_model=GarminOut)
def start_backfill(
    request: Request, profile: ProfileDep, session: SessionDep, body: BackfillIn
) -> GarminOut:
    if not has_tokens(get_household(request).settings.profile_tokens_dir(profile.slug)):
        raise HTTPException(409, "Log in to Garmin first")
    if not profile.runner.start_backfill(body.days):
        raise HTTPException(409, "A sync is running. Try again when it is done.")
    return garmin_out(request, profile, session)
