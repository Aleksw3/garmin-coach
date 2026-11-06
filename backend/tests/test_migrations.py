from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

import garmin_coach.models  # noqa: F401
from garmin_coach.db import BUSY_TIMEOUT_MS, Base, create_db_engine, include_object
from garmin_coach.migrate import MIGRATIONS_DIR


def test_migrations_match_models(database_url: str) -> None:
    with create_db_engine(database_url).connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"render_as_batch": True, "include_object": include_object}
        )
        assert compare_metadata(context, Base.metadata) == []


def test_shortened_chat_titles_get_the_first_line_back(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'coach.db'}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0010")
    question = "How should I split hill sessions and long runs over the next eight weeks?"
    with create_db_engine(url).begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO conversation (id, kind, title, created_at, updated_at) VALUES "
                "(1, 'chat', :cut, '2026-11-01', '2026-11-01'), "
                "(2, 'chat', 'Short title', '2026-11-01', '2026-11-01')"
            ),
            {"cut": question[:57] + "..."},
        )
        connection.execute(
            sa.text(
                "INSERT INTO message (conversation_id, role, content, display_text, source, "
                "created_at) VALUES (1, 'user', '[]', :text, 'user', '2026-11-01')"
            ),
            {"text": f"{question}\nMore detail"},
        )
    command.upgrade(config, "head")
    with create_db_engine(url).connect() as connection:
        titles = connection.execute(sa.text("SELECT title FROM conversation ORDER BY id"))
        assert list(titles.scalars()) == [question, "Short title"]


def test_connections_use_wal_without_waiting_on_every_commit(database_url: str) -> None:
    expected = {"journal_mode": "wal", "synchronous": 1, "busy_timeout": BUSY_TIMEOUT_MS}
    with create_db_engine(database_url).connect() as connection:
        actual = {name: connection.execute(sa.text(f"PRAGMA {name}")).scalar() for name in expected}
    assert actual == expected
