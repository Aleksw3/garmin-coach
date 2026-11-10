from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.agent import Coach
from garmin_coach.coach.notify import NO_NOTIFIER, Sender
from garmin_coach.coach.proactive import ProactiveCoach
from garmin_coach.garmin.connect import PendingLogin
from garmin_coach.garmin.nightly import TomorrowOnWatch
from garmin_coach.garmin.source import GarminSource
from garmin_coach.jobs import SyncRunner
from garmin_coach.sync import SyncService

PROFILE_HEADER = "X-Profile"


@dataclass
class ProfileRuntime:
    slug: str
    sessions: sessionmaker[Session]
    coach: Coach
    runner: SyncRunner
    notifier: Sender
    proactive: ProactiveCoach | None = None
    watch: TomorrowOnWatch | None = None
    pending_login: PendingLogin | None = None

    def garmin(self) -> GarminSource:
        return self.runner.make_service().source


def make_profile(
    slug: str,
    sessions: sessionmaker[Session],
    make_sync_service: Callable[[], SyncService],
    coach: Coach,
    proactive: ProactiveCoach | None = None,
    notifier: Sender = NO_NOTIFIER,
) -> ProfileRuntime:
    runner = SyncRunner(
        make_sync_service,
        on_synced=proactive.after_sync if proactive else None,
        on_auth_failed=lambda error: notifier.send(
            "Garmin login failed",
            f"The sync could not log in to Garmin: {error}. Log in again on the Settings page.",
            "#settings",
        ),
    )
    watch = TomorrowOnWatch(sessions, lambda: runner.make_service().source, notifier)
    return ProfileRuntime(slug, sessions, coach, runner, notifier, proactive, watch)


def current_profile(request: Request) -> ProfileRuntime:
    profiles: dict[str, ProfileRuntime] = request.app.state.profiles
    slug = request.headers.get(PROFILE_HEADER) or request.query_params.get("profile")
    if slug is None and len(profiles) == 1:
        return next(iter(profiles.values()))
    if slug not in profiles:
        raise HTTPException(409, "Choose a profile first")
    return profiles[slug]


ProfileDep = Annotated[ProfileRuntime, Depends(current_profile)]


def get_session(profile: ProfileDep) -> Iterator[Session]:
    with profile.sessions() as session:
        yield session


def get_research(request: Request) -> Iterator[Session]:
    with request.app.state.research() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
ResearchDep = Annotated[Session, Depends(get_research)]
