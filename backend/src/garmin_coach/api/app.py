from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.api.activity_routes import router as activity_router
from garmin_coach.api.coach_routes import router as coach_router
from garmin_coach.api.evidence_routes import router as evidence_router
from garmin_coach.api.hill_routes import router as hill_router
from garmin_coach.api.plan_routes import router as plan_router
from garmin_coach.api.profile import ProfileRuntime
from garmin_coach.api.routes import router
from garmin_coach.api.setup_routes import router as setup_router
from garmin_coach.api.zone_routes import router as zone_router
from garmin_coach.evidence.fetch import EvidenceFetcher
from garmin_coach.garmin.connect import GarminWebLogin
from garmin_coach.household import Household
from garmin_coach.jobs import DEFAULT_SCHEDULE, Schedule, ScheduledProfile, start_scheduler
from garmin_coach.version import Version, running_version


def create_app(
    profiles: list[ProfileRuntime],
    research: sessionmaker[Session],
    frontend_dir: Path | None = None,
    schedule_sync: bool = True,
    schedule: Schedule = DEFAULT_SCHEDULE,
    evidence_fetcher: EvidenceFetcher | None = None,
    household: Household | None = None,
    garmin_login: GarminWebLogin | None = None,
    backup: Callable[[], object] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = (
            start_scheduler(
                [
                    ScheduledProfile(p.slug, p.runner, p.proactive, p.watch)
                    for p in app.state.profiles.values()
                ],
                schedule,
                app.state.evidence_fetcher,
                backup,
            )
            if schedule_sync
            else None
        )
        app.state.scheduler = scheduler
        yield
        app.state.scheduler = None
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Garmin coach", lifespan=lifespan)
    app.state.profiles = (
        household.profiles if household else {profile.slug: profile for profile in profiles}
    )
    app.state.research = research
    app.state.evidence_fetcher = household.fetcher if household else evidence_fetcher
    app.state.schedule = schedule
    app.state.scheduler = None
    app.state.household = household
    app.state.garmin_login = garmin_login or GarminWebLogin()
    app.include_router(router)
    app.include_router(coach_router)
    app.include_router(plan_router)
    app.include_router(activity_router)
    app.include_router(evidence_router)
    app.include_router(zone_router)
    app.include_router(hill_router)
    app.include_router(setup_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    version = running_version()

    @app.get("/api/version")
    def get_version() -> Version:
        return version

    if frontend_dir is not None and frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app
