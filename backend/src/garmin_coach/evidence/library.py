import re
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from garmin_coach.db import FTS_TABLE
from garmin_coach.models import Evidence, EvidenceTopic
from garmin_coach.sync import get_state, set_state

TOPICS_SEEDED = "evidence_topics_seeded"
SEARCH_LIMIT = 8
STATUSES = ("pending", "approved", "rejected")

DEFAULT_TOPICS = (
    (
        "Running",
        "(trail running[tiab] OR mountain running[tiab] OR ultramarathon[tiab] OR "
        "ultra-marathon[tiab] OR downhill running[tiab] OR running economy[tiab] OR "
        "((strength training[tiab] OR resistance training[tiab]) AND "
        "(runners[tiab] OR running performance[tiab])))",
        5,
    ),
    (
        "Strength training",
        "((strength training[tiab] OR resistance training[tiab]) AND (athletes[tiab] OR "
        "maximal strength[tiab] OR hypertrophy[tiab] OR training volume[tiab]))",
        2,
    ),
    (
        "Cross-country skiing",
        "(cross-country skiing[tiab] OR cross-country skiers[tiab] OR cross-country skier[tiab])",
        2,
    ),
    (
        "Ski touring",
        "(ski mountaineering[tiab] OR ski touring[tiab] OR skimo[tiab] OR ski mountaineers[tiab])",
        2,
    ),
    (
        "Cycling and commuting",
        "(active commuting[tiab] OR bicycle commuting[tiab] OR commuter cycling[tiab] OR "
        "cycling to work[tiab])",
        2,
    ),
    (
        "General training research",
        "((training intensity distribution[tiab] OR polarized training[tiab] OR "
        "polarised training[tiab] OR heart rate variability-guided[tiab] OR HRV-guided[tiab] "
        "OR tapering[tiab] OR concurrent training[tiab] OR overreaching[tiab]) AND "
        "(endurance[tiab] OR athletes[tiab]))",
        2,
    ),
)

SEED_PMIDS = (
    "20861519",
    "23914932",
    "29249083",
    "17849143",
    "23852425",
    "32502973",
    "12183501",
)


def seed_topics(session: Session) -> None:
    if get_state(session, TOPICS_SEEDED):
        return
    for name, query, limit in DEFAULT_TOPICS:
        session.add(EvidenceTopic(name=name, query=query, weekly_limit=limit, active=True))
    set_state(session, TOPICS_SEEDED, "yes")


def citation(entry: Evidence) -> str:
    authors = entry.authors.split("; ")
    first = authors[0] if authors and authors[0] else "Unknown"
    who = f"{first} et al." if len(authors) > 1 else first
    return f"{who} ({entry.year or 'n.d.'}), {entry.journal or 'no journal'}"


def index_entry(session: Session, entry: Evidence) -> None:
    session.execute(text(f"DELETE FROM {FTS_TABLE} WHERE rowid = :id"), {"id": entry.id})
    if entry.status != "approved":
        return
    session.execute(
        text(
            f"INSERT INTO {FTS_TABLE} "
            "(rowid, title, claim, takeaway, population, intervention, outcome) "
            "VALUES (:id, :title, :claim, :takeaway, :population, :intervention, :outcome)"
        ),
        {
            "id": entry.id,
            "title": entry.title,
            "claim": entry.claim,
            "takeaway": entry.takeaway,
            "population": entry.population,
            "intervention": entry.intervention,
            "outcome": entry.outcome,
        },
    )


def set_status(session: Session, entry: Evidence, status: str, now: datetime) -> None:
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status}")
    entry.status = status
    entry.reviewed_at = None if status == "pending" else now
    session.flush()
    index_entry(session, entry)


def match_query(query: str) -> str | None:
    words = [word for word in re.findall(r"\w+", query.lower()) if len(word) > 2]
    return " OR ".join(f'"{word}"' for word in words) or None


def search(session: Session, query: str, limit: int = SEARCH_LIMIT) -> list[Evidence]:
    terms = match_query(query)
    if terms is None:
        return []
    ids = session.scalars(
        text(
            f"SELECT rowid FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH :terms ORDER BY rank LIMIT :n"
        ),
        {"terms": terms, "n": limit},
    ).all()
    entries = {e.id: e for e in session.scalars(select(Evidence).where(Evidence.id.in_(ids)))}
    return [entries[i] for i in ids if i in entries]
