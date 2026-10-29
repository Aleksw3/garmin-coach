import gzip
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import RawActivity, RawDaily


def encode(data: Any) -> bytes:
    return gzip.compress(json.dumps(data, separators=(",", ":")).encode(), compresslevel=6)


def decode(body: bytes) -> Any:
    return json.loads(gzip.decompress(body))


def put_activity(session: Session, garmin_id: int, endpoint: str, data: Any) -> None:
    session.merge(
        RawActivity(
            garmin_id=garmin_id, endpoint=endpoint, fetched_at=datetime.now(), body=encode(data)
        )
    )


def get_activity(session: Session, garmin_id: int, endpoint: str) -> Any | None:
    row = session.get(RawActivity, (garmin_id, endpoint))
    return None if row is None else decode(row.body)


def activity_endpoints(session: Session, garmin_id: int) -> set[str]:
    rows = session.scalars(select(RawActivity.endpoint).where(RawActivity.garmin_id == garmin_id))
    return set(rows)


def activity_ids(session: Session) -> list[int]:
    rows = session.scalars(select(RawActivity.garmin_id).where(RawActivity.endpoint == "summary"))
    return list(rows)


def put_daily(session: Session, day: date, kind: str, data: Any) -> None:
    session.merge(RawDaily(day=day, kind=kind, fetched_at=datetime.now(), body=encode(data)))


def get_daily(session: Session, day: date, kind: str) -> Any | None:
    row = session.get(RawDaily, (day, kind))
    return None if row is None else decode(row.body)


def daily_kinds(session: Session, day: date) -> set[str]:
    return set(session.scalars(select(RawDaily.kind).where(RawDaily.day == day)))


def daily_days(session: Session, kind: str | None = None) -> list[date]:
    query = select(RawDaily.day).distinct()
    if kind is not None:
        query = query.where(RawDaily.kind == kind)
    return sorted(session.scalars(query))
