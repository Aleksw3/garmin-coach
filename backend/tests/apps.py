from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.api.app import create_app
from garmin_coach.api.profile import make_profile
from garmin_coach.coach.agent import Coach
from garmin_coach.sync import SyncService


def single_app(
    sessions: sessionmaker[Session],
    make_service: Callable[[], SyncService],
    coach: Coach,
    **options: Any,
) -> FastAPI:
    options.setdefault("schedule_sync", False)
    profile = make_profile("me", sessions, make_service, coach)
    return create_app([profile], sessions, **options)
