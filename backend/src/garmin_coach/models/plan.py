from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from garmin_coach.db import Base


class Plan(Base):
    __tablename__ = "plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goal.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PlannedSession(Base):
    __tablename__ = "planned_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    sport: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    duration_min: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    intensity: Mapped[str | None] = mapped_column(String(200))
    steps: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")
    exercises: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")
    description: Mapped[str | None] = mapped_column(Text)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    garmin_workout_id: Mapped[int | None] = mapped_column(BigInteger)
    garmin_schedule_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_to_watch_at: Mapped[datetime | None] = mapped_column(DateTime)


class PlanProposal(Base):
    __tablename__ = "plan_proposal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    summary: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class SessionMatch(Base):
    __tablename__ = "session_match"

    planned_session_id: Mapped[int] = mapped_column(
        ForeignKey("planned_session.id", ondelete="CASCADE"), primary_key=True
    )
    activity_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    compliance: Mapped[float | None] = mapped_column(Float)
    details: Mapped[str] = mapped_column(Text)


class SeasonWeek(Base):
    __tablename__ = "season_week"

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goal.id", ondelete="SET NULL"))
    phase: Mapped[str] = mapped_column(String(16))
    hours: Mapped[float] = mapped_column(Float)
    climb_m: Mapped[float | None] = mapped_column(Float)
    longest_h: Mapped[float | None] = mapped_column(Float)
    focus: Mapped[str | None] = mapped_column(Text)
