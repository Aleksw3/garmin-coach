from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from garmin_coach.db import Base


class EvidenceTopic(Base):
    __tablename__ = "evidence_topic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    query: Mapped[str] = mapped_column(Text)
    weekly_limit: Mapped[int] = mapped_column(Integer, default=2)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence_topic.id", ondelete="SET NULL")
    )
    pmid: Mapped[str] = mapped_column(String(16), unique=True)
    doi: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[str] = mapped_column(Text)
    journal: Mapped[str | None] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer)
    abstract: Mapped[str] = mapped_column(Text)
    publication_types: Mapped[str] = mapped_column(Text)
    design: Mapped[str] = mapped_column(String(32))
    grade: Mapped[str] = mapped_column(String(1))
    claim: Mapped[str] = mapped_column(Text)
    population: Mapped[str] = mapped_column(Text)
    intervention: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    effect: Mapped[str] = mapped_column(String(16))
    takeaway: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    disputed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
