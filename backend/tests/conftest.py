from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.db import create_db_engine, session_factory
from garmin_coach.migrate import upgrade_database
from garmin_coach.normalize.sports import seed_sport_mapping


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'coach.db'}"
    upgrade_database(url)
    return url


@pytest.fixture
def sessions(database_url: str) -> sessionmaker[Session]:
    factory = session_factory(create_db_engine(database_url))
    with factory() as session:
        seed_sport_mapping(session)
        session.commit()
    return factory


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    with sessions() as session:
        yield session
