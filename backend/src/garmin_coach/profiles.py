import re
import sqlite3
import unicodedata
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.config import Settings, sqlite_url
from garmin_coach.db import FTS_TABLE, create_db_engine, session_factory
from garmin_coach.evidence.fetch import LAST_FETCH
from garmin_coach.evidence.library import TOPICS_SEEDED, seed_topics
from garmin_coach.migrate import upgrade_database
from garmin_coach.models import AthleteProfile
from garmin_coach.normalize.sports import seed_sport_mapping

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
SHARED_TABLES = ("evidence_topic", "evidence")
SHARED_STATE = (LAST_FETCH, TOPICS_SEEDED)
LETTERS = str.maketrans({"æ": "ae", "ø": "o", "ß": "ss", "þ": "th", "ð": "d", "đ": "d", "ł": "l"})


class ProfileError(ValueError):
    pass


def check_slug(slug: str) -> str:
    if not SLUG.fullmatch(slug):
        raise ProfileError(f"Profile names use lowercase letters, digits and dashes, not {slug!r}")
    return slug


def slug_for(name: str, taken: set[str]) -> str:
    plain = unicodedata.normalize("NFKD", name.lower().translate(LETTERS))
    base = re.sub(r"[^a-z0-9]+", "-", plain.encode("ascii", "ignore").decode()).strip("-")
    base = base[:28].strip("-") or "person"
    slug, number = base, 2
    while slug in taken:
        slug, number = f"{base}-{number}", number + 1
    return slug


def profile_slugs(settings: Settings) -> list[str]:
    if not settings.profiles_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in settings.profiles_dir.iterdir()
        if SLUG.fullmatch(path.name) and (path / "coach.db").exists()
    )


def open_sessions(path: Path) -> sessionmaker[Session]:
    url = sqlite_url(path)
    upgrade_database(url)
    return session_factory(create_db_engine(url))


def open_profile(settings: Settings, slug: str) -> sessionmaker[Session]:
    if check_slug(slug) not in profile_slugs(settings):
        raise ProfileError(f"No profile {slug!r}. Create it with: coach profile add {slug}")
    sessions = open_sessions(settings.profile_database_path(slug))
    with sessions() as session:
        seed_sport_mapping(session)
        session.commit()
    return sessions


def open_research(settings: Settings) -> sessionmaker[Session]:
    sessions = open_sessions(settings.research_database_path)
    settings.research_database_path.chmod(0o600)
    with sessions() as session:
        seed_topics(session)
        session.commit()
    return sessions


def athlete(session: Session) -> AthleteProfile:
    profile = session.get(AthleteProfile, 1)
    if profile is None:
        profile = AthleteProfile(id=1)
        session.add(profile)
    return profile


def profile_name(session: Session, slug: str) -> str:
    name = session.scalar(select(AthleteProfile.name).where(AthleteProfile.id == 1))
    return name or slug.replace("-", " ").title()


def create_profile(settings: Settings, slug: str, name: str | None, trimp: float) -> None:
    check_slug(slug)
    if slug in profile_slugs(settings):
        raise ProfileError(f"Profile {slug!r} already exists")
    sessions = open_sessions(settings.profile_database_path(slug))
    with sessions() as session:
        profile = athlete(session)
        profile.name = name
        profile.trimp_coefficient = trimp
        session.commit()


def move_shared_data(profile_db: Path, research_db: Path) -> int:
    connection = sqlite3.connect(research_db)
    try:
        if connection.execute("SELECT count(*) FROM evidence").fetchone()[0] > 0:
            return 0
        connection.execute("ATTACH DATABASE ? AS profile", (str(profile_db),))
        with connection:
            connection.execute("DELETE FROM evidence_topic")
            connection.execute(f"DELETE FROM {FTS_TABLE}")
            for table in SHARED_TABLES:
                connection.execute(f"INSERT INTO {table} SELECT * FROM profile.{table}")
            connection.execute(
                f"INSERT INTO {FTS_TABLE}(rowid, title, claim, takeaway, population, "
                "intervention, outcome) SELECT rowid, title, claim, takeaway, population, "
                f"intervention, outcome FROM profile.{FTS_TABLE}"
            )
            marks = ", ".join("?" for _ in SHARED_STATE)
            connection.execute(f"DELETE FROM sync_state WHERE key IN ({marks})", SHARED_STATE)
            connection.execute(
                f"INSERT INTO sync_state SELECT * FROM profile.sync_state WHERE key IN ({marks})",
                SHARED_STATE,
            )
            columns = (
                "created_at, model, purpose, conversation_id, input_tokens, "
                "cache_write_tokens, cache_read_tokens, output_tokens, cost_usd"
            )
            connection.execute(
                f"INSERT INTO api_usage ({columns}) SELECT {columns} FROM profile.api_usage "
                "WHERE purpose = 'evidence'"
            )
            connection.execute("DELETE FROM profile.api_usage WHERE purpose = 'evidence'")
        count: int = connection.execute("SELECT count(*) FROM evidence").fetchone()[0]
        return count
    finally:
        connection.close()


def adopt_single_database(
    settings: Settings, slug: str, ntfy_topic: str | None, trimp: float
) -> int:
    check_slug(slug)
    source = settings.single_database_path
    if not source.exists():
        raise ProfileError(f"No database at {source} to move")
    if profile_slugs(settings):
        raise ProfileError("Profiles exist already, so there is nothing to move")
    upgrade_database(sqlite_url(source))
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()

    target = settings.profile_dir(slug)
    target.mkdir(parents=True)
    for suffix in ("", "-wal", "-shm"):
        part = source.with_name(source.name + suffix)
        if part.exists():
            part.rename(target / part.name)
    if settings.single_tokens_dir.is_dir():
        settings.single_tokens_dir.rename(settings.profile_tokens_dir(slug))

    open_sessions(settings.research_database_path)
    moved = move_shared_data(settings.profile_database_path(slug), settings.research_database_path)
    sessions = open_profile(settings, slug)
    with sessions() as session:
        profile = athlete(session)
        profile.ntfy_topic = profile.ntfy_topic or ntfy_topic
        profile.trimp_coefficient = profile.trimp_coefficient or trimp
        session.commit()
    return moved
