from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import garmin_coach.models  # noqa: F401
from garmin_coach.db import Base, create_db_engine


def test_migrations_match_models(database_url: str) -> None:
    with create_db_engine(database_url).connect() as connection:
        context = MigrationContext.configure(connection, opts={"render_as_batch": True})
        assert compare_metadata(context, Base.metadata) == []
