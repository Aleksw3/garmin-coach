from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from garmin_coach.db import Base


class SportMapping(Base):
    __tablename__ = "sport_mapping"

    type_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    sport_group: Mapped[str] = mapped_column(String(32))


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    type_key: Mapped[str] = mapped_column(String(64), index=True)
    start_time_local: Mapped[datetime] = mapped_column(DateTime)
    start_time_gmt: Mapped[datetime] = mapped_column(DateTime)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    duration_s: Mapped[float | None] = mapped_column(Float)
    moving_s: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float)
    min_elevation_m: Mapped[float | None] = mapped_column(Float)
    max_elevation_m: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float)
    avg_grade_adjusted_speed_mps: Mapped[float | None] = mapped_column(Float)
    avg_power_w: Mapped[float | None] = mapped_column(Float)
    normalized_power_w: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    training_load: Mapped[float | None] = mapped_column(Float)
    aerobic_training_effect: Mapped[float | None] = mapped_column(Float)
    anaerobic_training_effect: Mapped[float | None] = mapped_column(Float)
    training_effect_label: Mapped[str | None] = mapped_column(String(64))
    vo2max: Mapped[float | None] = mapped_column(Float)
    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lon: Mapped[float | None] = mapped_column(Float)
    end_lat: Mapped[float | None] = mapped_column(Float)
    end_lon: Mapped[float | None] = mapped_column(Float)
    location_name: Mapped[str | None] = mapped_column(String(200))
    lap_count: Mapped[int | None] = mapped_column(Integer)
    is_commute: Mapped[bool] = mapped_column(Boolean, default=False)
    commute_override: Mapped[bool | None] = mapped_column(Boolean)


class ActivityLap(Base):
    __tablename__ = "activity_lap"

    activity_id: Mapped[int] = mapped_column(
        ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True
    )
    lap_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_time_gmt: Mapped[datetime | None] = mapped_column(DateTime)
    distance_m: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    moving_s: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    avg_speed_mps: Mapped[float | None] = mapped_column(Float)
    avg_grade_adjusted_speed_mps: Mapped[float | None] = mapped_column(Float)
    avg_power_w: Mapped[float | None] = mapped_column(Float)
    intensity_type: Mapped[str | None] = mapped_column(String(32))


class ActivityZoneTime(Base):
    __tablename__ = "activity_zone_time"

    activity_id: Mapped[int] = mapped_column(
        ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    zone: Mapped[int] = mapped_column(Integer, primary_key=True)
    seconds: Mapped[float] = mapped_column(Float)
    low_boundary: Mapped[float | None] = mapped_column(Float)


class StrengthSet(Base):
    __tablename__ = "strength_set"

    activity_id: Mapped[int] = mapped_column(
        ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True
    )
    set_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_type: Mapped[str] = mapped_column(String(16))
    exercise_category: Mapped[str | None] = mapped_column(String(64))
    exercise_name: Mapped[str | None] = mapped_column(String(64))
    reps: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    start_time_gmt: Mapped[datetime | None] = mapped_column(DateTime)


class StrengthSetOverride(Base):
    __tablename__ = "strength_set_override"

    activity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    set_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_category: Mapped[str | None] = mapped_column(String(64))
    exercise_name: Mapped[str | None] = mapped_column(String(64))
    reps: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
