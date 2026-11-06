from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


FTS_TABLE = "evidence_fts"
BUSY_TIMEOUT_MS = 30_000


def include_object(_object: Any, name: str | None, type_: str, *_: Any) -> bool:
    return not (type_ == "table" and name is not None and name.startswith(FTS_TABLE))


def create_db_engine(url: str) -> Engine:
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection: Any, _record: Any) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        # With WAL a power cut can lose the last commits but never corrupts the file, and
        # commits no longer wait on a slow SD card while they hold the write lock.
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
