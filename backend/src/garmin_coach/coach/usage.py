from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.models import ApiUsage


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write: float
    cache_read: float


PER_MILLION = {
    "claude-opus-5-5": Price(4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": Price(2.0, 10.0, 2.50, 0.20),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.125, 0.01),
}
UNKNOWN_MODEL_PRICE = PER_MILLION["claude-opus-5-5"]


def cost_usd(
    model: str, input_tokens: int, cache_write: int, cache_read: int, output: int
) -> float:
    price = PER_MILLION.get(model, UNKNOWN_MODEL_PRICE)
    total = (
        input_tokens * price.input
        + cache_write * price.cache_write
        + cache_read * price.cache_read
        + output * price.output
    )
    return total / 1_000_000


def record_usage(
    session: Session, model: str, purpose: str, conversation_id: int | None, usage: Any
) -> ApiUsage:
    input_tokens = usage.input_tokens or 0
    cache_write = usage.cache_creation_input_tokens or 0
    cache_read = usage.cache_read_input_tokens or 0
    output = usage.output_tokens or 0
    row = ApiUsage(
        created_at=datetime.now(),
        model=model,
        purpose=purpose,
        conversation_id=conversation_id,
        input_tokens=input_tokens,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
        output_tokens=output,
        cost_usd=cost_usd(model, input_tokens, cache_write, cache_read, output),
    )
    session.add(row)
    return row


def month_start(day: date) -> datetime:
    return datetime(day.year, day.month, 1)


def month_spend(session: Session, day: date) -> float:
    total = session.scalar(
        select(func.sum(ApiUsage.cost_usd)).where(ApiUsage.created_at >= month_start(day))
    )
    return float(total or 0.0)


@dataclass(frozen=True)
class DaySpend:
    day: date
    purpose: str
    cost_usd: float
    calls: int


def daily_spend(session: Session, since: date) -> list[DaySpend]:
    call_day = func.date(ApiUsage.created_at)
    rows = session.execute(
        select(call_day, ApiUsage.purpose, func.sum(ApiUsage.cost_usd), func.count(ApiUsage.id))
        .where(ApiUsage.created_at >= datetime.combine(since, time()))
        .group_by(call_day, ApiUsage.purpose)
    )
    return [
        DaySpend(date.fromisoformat(day), purpose, float(cost), calls)
        for day, purpose, cost, calls in rows
    ]


class Spending:
    def __init__(self, sources: Sequence[sessionmaker[Session]]) -> None:
        self.sources = list(sources)

    def __call__(self, day: date) -> float:
        total = 0.0
        for sessions in self.sources:
            with sessions() as session:
                total += month_spend(session, day)
        return total

    def daily(self, since: date) -> list[DaySpend]:
        totals: dict[tuple[date, str], DaySpend] = {}
        for sessions in self.sources:
            with sessions() as session:
                for row in daily_spend(session, since):
                    earlier = totals.get((row.day, row.purpose))
                    if earlier is not None:
                        row = replace(
                            row,
                            cost_usd=earlier.cost_usd + row.cost_usd,
                            calls=earlier.calls + row.calls,
                        )
                    totals[(row.day, row.purpose)] = row
        return sorted(totals.values(), key=lambda row: (row.day, row.purpose))
