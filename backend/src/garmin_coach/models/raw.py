from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from garmin_coach.db import Base


class RawActivity(Base):
    __tablename__ = "raw_activity"

    garmin_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(32), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    body: Mapped[bytes] = mapped_column(LargeBinary)


class RawDaily(Base):
    __tablename__ = "raw_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    body: Mapped[bytes] = mapped_column(LargeBinary)
