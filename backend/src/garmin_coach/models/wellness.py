from datetime import date

from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from garmin_coach.db import Base


class DailyWellness(Base):
    __tablename__ = "daily_wellness"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int | None] = mapped_column(Integer)
    resting_hr: Mapped[int | None] = mapped_column(Integer)
    resting_hr_7d_avg: Mapped[int | None] = mapped_column(Integer)
    avg_stress: Mapped[int | None] = mapped_column(Integer)
    max_stress: Mapped[int | None] = mapped_column(Integer)
    body_battery_high: Mapped[int | None] = mapped_column(Integer)
    body_battery_low: Mapped[int | None] = mapped_column(Integer)
    body_battery_at_wake: Mapped[int | None] = mapped_column(Integer)
    floors_ascended_m: Mapped[float | None] = mapped_column(Float)
    sleep_s: Mapped[int | None] = mapped_column(Integer)
    deep_sleep_s: Mapped[int | None] = mapped_column(Integer)
    light_sleep_s: Mapped[int | None] = mapped_column(Integer)
    rem_sleep_s: Mapped[int | None] = mapped_column(Integer)
    awake_s: Mapped[int | None] = mapped_column(Integer)
    sleep_score: Mapped[int | None] = mapped_column(Integer)
    sleep_avg_hr: Mapped[float | None] = mapped_column(Float)
    sleep_avg_respiration: Mapped[float | None] = mapped_column(Float)
    sleep_avg_stress: Mapped[float | None] = mapped_column(Float)
    hrv_last_night: Mapped[int | None] = mapped_column(Integer)
    hrv_weekly_avg: Mapped[int | None] = mapped_column(Integer)
    hrv_5min_high: Mapped[int | None] = mapped_column(Integer)
    hrv_status: Mapped[str | None] = mapped_column(String(32))
    hrv_baseline_low: Mapped[int | None] = mapped_column(Integer)
    hrv_baseline_high: Mapped[int | None] = mapped_column(Integer)
    readiness_score: Mapped[int | None] = mapped_column(Integer)
    readiness_level: Mapped[str | None] = mapped_column(String(32))
    readiness_feedback: Mapped[str | None] = mapped_column(String(64))
    acute_load: Mapped[float | None] = mapped_column(Float)
    training_status: Mapped[str | None] = mapped_column(String(32))
    training_status_phrase: Mapped[str | None] = mapped_column(String(64))
    vo2max: Mapped[float | None] = mapped_column(Float)


class BodyComposition(Base):
    __tablename__ = "body_composition"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float)
    muscle_mass_kg: Mapped[float | None] = mapped_column(Float)
    bmi: Mapped[float | None] = mapped_column(Float)
