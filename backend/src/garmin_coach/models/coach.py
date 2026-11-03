from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from garmin_coach.db import Base


class AthleteProfile(Base):
    __tablename__ = "athlete_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(100))
    birth_year: Mapped[int | None] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(16))
    height_cm: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    training_days: Mapped[str | None] = mapped_column(Text)
    injuries: Mapped[str | None] = mapped_column(Text)
    equipment: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class Goal(Base):
    __tablename__ = "goal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    target_date: Mapped[date | None] = mapped_column(Date)
    target: Mapped[str | None] = mapped_column(String(200))
    distance_km: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    terrain: Mapped[str | None] = mapped_column(Text)
    cutoffs: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(1), default="A")
    status: Mapped[str] = mapped_column(String(16), default="active")


class CoachNote(Base):
    __tablename__ = "coach_note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    text: Mapped[str] = mapped_column(Text)


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="chat", server_default="chat")
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    display_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ApiUsage(Base):
    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32))
    conversation_id: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)


class ActivityFeedback(Base):
    __tablename__ = "activity_feedback"

    activity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ThresholdTest(Base):
    __tablename__ = "threshold_test"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    lt1_hr: Mapped[int] = mapped_column(Integer)
    lt2_hr: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(32))
    activity_id: Mapped[int | None] = mapped_column(BigInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
