from datetime import date, timedelta
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import PlannedSession, UnavailablePeriod

Reason = Literal["travel", "illness", "injury", "work", "other"]
CONTEXT_DAYS_AHEAD = 14
MAX_PERIOD_DAYS = 120


class PeriodSpec(BaseModel):
    first_day: date
    last_day: date
    reason: Reason
    note: str | None = Field(
        default=None,
        max_length=500,
        description="What is still possible, for example hotel gym only or easy walks",
    )

    @model_validator(mode="after")
    def check_days(self) -> Self:
        if self.last_day < self.first_day:
            raise ValueError("last_day is before first_day")
        if (self.last_day - self.first_day).days >= MAX_PERIOD_DAYS:
            raise ValueError(f"a period can cover at most {MAX_PERIOD_DAYS} days")
        return self


def periods_between(session: Session, first: date, last: date) -> list[UnavailablePeriod]:
    return list(
        session.scalars(
            select(UnavailablePeriod)
            .where(UnavailablePeriod.first_day <= last, UnavailablePeriod.last_day >= first)
            .order_by(UnavailablePeriod.first_day)
        )
    )


def add_period(session: Session, spec: PeriodSpec) -> UnavailablePeriod:
    period = UnavailablePeriod(**spec.model_dump())
    period.note = period.note or None
    session.add(period)
    session.flush()
    return period


def period_text(period: UnavailablePeriod) -> str:
    days = (
        f"{period.first_day}"
        if period.first_day == period.last_day
        else f"{period.first_day} to {period.last_day}"
    )
    return f"{days} {period.reason}" + (f" ({period.note})" if period.note else "")


def sessions_in(session: Session, period: UnavailablePeriod) -> list[PlannedSession]:
    return list(
        session.scalars(
            select(PlannedSession)
            .where(
                PlannedSession.day.between(period.first_day, period.last_day),
                PlannedSession.skipped.is_(False),
            )
            .order_by(PlannedSession.day)
        )
    )


def unavailable_line(session: Session, today: date) -> str | None:
    periods = periods_between(session, today, today + timedelta(days=CONTEXT_DAYS_AHEAD))
    if not periods:
        return None
    return "Cannot train as normal: " + "; ".join(period_text(p) for p in periods)
