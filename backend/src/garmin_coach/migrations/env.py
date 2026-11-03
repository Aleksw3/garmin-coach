from alembic import context

import garmin_coach.models  # noqa: F401
from garmin_coach.config import get_settings, sqlite_url
from garmin_coach.db import Base, create_db_engine, include_object

url = context.config.get_main_option("sqlalchemy.url") or sqlite_url(
    get_settings().research_database_path
)


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        render_as_batch=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=Base.metadata,
                render_as_batch=True,
                include_object=include_object,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
