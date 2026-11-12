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


def test_adding_the_descent_scan_keeps_the_rows_that_belong_to_activities(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'coach.db'}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0018")
    with create_db_engine(url).begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO activity (id, type_key, start_time_local, start_time_gmt, "
                "local_date, is_commute) VALUES "
                "(1, 'running', '2026-11-01 08:00', '2026-11-01 07:00', '2026-11-01', 0)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO activity_heart_rate (activity_id, bpm, seconds) VALUES (1, 140, 60)"
            )
        )
    command.upgrade(config, "head")
    with create_db_engine(url).connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM activity_heart_rate")).scalar() == 1
        assert connection.execute(sa.text("SELECT descents_scanned FROM activity")).scalar() == 0
