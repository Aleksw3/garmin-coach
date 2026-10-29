from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.api.coach_routes import router as coach_router
from garmin_coach.api.routes import router
from garmin_coach.coach.agent import Coach
from garmin_coach.jobs import SyncRunner, start_scheduler
from garmin_coach.sync import SyncService


def create_app(
    sessions: sessionmaker[Session],
    make_sync_service: Callable[[], SyncService],
    coach: Coach,
    frontend_dir: Path | None = None,
    schedule_sync: bool = True,
) -> FastAPI:
    runner = SyncRunner(make_sync_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = start_scheduler(runner) if schedule_sync else None
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Garmin coach", lifespan=lifespan)
    app.state.sessions = sessions
    app.state.sync_runner = runner
    app.state.coach = coach
    app.include_router(router)
    app.include_router(coach_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if frontend_dir is not None and frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app
