from datetime import date, datetime

from pydantic import BaseModel


class WellnessOut(BaseModel):
    day: date
    sleep_day: date | None
    sleep_h: float | None
    sleep_score: int | None
    hrv_last_night: int | None
    hrv_status: str | None
    resting_hr: int | None
    readiness_score: int | None
    readiness_level: str | None
    training_status: str | None
    body_battery_at_wake: int | None


class BaselineOut(BaseModel):
    day: date
    rolling: float
    low: float
    high: float
    status: str


class LoadOut(BaseModel):
    day: date
    load: float
    acute: float
    chronic: float


class GroupTotalsOut(BaseModel):
    week_start: date
    sport_group: str
    activities: int
    distance_km: float
    hours: float
    elevation_gain_m: float


class ActivityOut(BaseModel):
    id: int
    name: str | None
    type_key: str
    sport_group: str
    start_time_local: datetime
    duration_s: float | None
    distance_km: float | None
    elevation_gain_m: float | None
    avg_hr: float | None
    training_load: float | None
    terrain: str | None
    is_commute: bool


class TodayOut(BaseModel):
    day: date
    wellness: WellnessOut | None
    hrv: BaselineOut | None
    resting_hr: BaselineOut | None
    load: LoadOut | None
    week: list[GroupTotalsOut]
    recent_activities: list[ActivityOut]


class HrvPointOut(BaseModel):
    day: date
    value: int | None
    rolling: float | None
    low: float | None
    high: float | None


class RunWeekOut(BaseModel):
    week_start: date
    runs: int
    distance_km: float
    hours: float
    elevation_gain_m: float
    elevation_loss_m: float
    longest_run_h: float
    flat_h: float
    rolling_h: float
    mountain_h: float
    back_to_back_long_days: int


class StrengthWeekOut(BaseModel):
    week_start: date
    sets_per_muscle: dict[str, float]


class OneRepMaxOut(BaseModel):
    exercise: str
    day: date
    kg: float


class TrendsOut(BaseModel):
    first_week: date
    last_week: date
    weekly_totals: list[GroupTotalsOut]
    load: list[LoadOut]
    hrv: list[HrvPointOut]
    run_weeks: list[RunWeekOut]
    strength_weeks: list[StrengthWeekOut]
    one_rep_max: list[OneRepMaxOut]


class SyncRunOut(BaseModel):
    started_at: datetime
    finished_at: datetime | None
    kind: str
    status: str
    calls: int
    failed_calls: int
    error: str | None


class SyncStatusOut(BaseModel):
    running: bool
    last_sync: str | None
    runs: list[SyncRunOut]
