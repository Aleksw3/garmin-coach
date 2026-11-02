from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.api.activity_routes import router as activity_router
from garmin_coach.api.coach_routes import router as coach_router
from garmin_coach.api.evidence_routes import router as evidence_router
from garmin_coach.api.plan_routes import router as plan_router
from garmin_coach.api.routes import router
from garmin_coach.coach.agent import Coach
from garmin_coach.coach.notify import NO_NOTIFIER, Notifier
from garmin_coach.coach.proactive import ProactiveCoach
from garmin_coach.evidence.fetch import EvidenceFetcher
from garmin_coach.jobs import DEFAULT_SCHEDULE, Schedule, SyncRunner, start_scheduler
from garmin_coach.sync import SyncService


def create_app(
    sessions: sessionmaker[Session],
    make_sync_service: Callable[[], SyncService],
    coach: Coach,
    frontend_dir: Path | None = None,
    schedule_sync: bool = True,
    proactive: ProactiveCoach | None = None,
    schedule: Schedule = DEFAULT_SCHEDULE,
    notifier: Notifier = NO_NOTIFIER,
    evidence_fetcher: EvidenceFetcher | None = None,
) -> FastAPI:
    runner = SyncRunner(
        make_sync_service,
        on_synced=proactive.activity_feedback if proactive else None,
        on_auth_failed=lambda error: notifier.send(
            "Garmin login failed", f"The sync could not log in to Garmin: {error}", "#settings"
        ),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = (
            start_scheduler(runner, proactive, schedule, evidence_fetcher)
            if schedule_sync
            else None
        )
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Garmin coach", lifespan=lifespan)
    app.state.sessions = sessions
    app.state.sync_runner = runner
    app.state.coach = coach
    app.state.notifier = notifier
    app.state.evidence_fetcher = evidence_fetcher
    app.state.schedule = schedule if proactive else None
    app.include_router(router)
    app.include_router(coach_router)
    app.include_router(plan_router)
    app.include_router(activity_router)
    app.include_router(evidence_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if frontend_dir is not None and frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app
