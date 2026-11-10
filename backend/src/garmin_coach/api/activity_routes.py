import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from garmin_coach.api.profile import SessionDep
from garmin_coach.api.routes import activity_out
from garmin_coach.api.schemas import ActivityOut
from garmin_coach.metrics.strength import MUSCLES_BY_CATEGORY
from garmin_coach.metrics.zones import activity_zone_seconds, current_zones
from garmin_coach.models import (
    Activity,
    ActivityFuel,
    ActivityLap,
    ActivityRating,
    ActivityZoneTime,
    PlannedSession,
    SessionMatch,
    StrengthSet,
    StrengthSetOverride,
)
from garmin_coach.normalize.sports import sport_groups

router = APIRouter(prefix="/api")


class LapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lap_index: int
    distance_m: float | None
    duration_s: float | None
    elevation_gain_m: float | None
    elevation_loss_m: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_speed_mps: float | None
    avg_grade_adjusted_speed_mps: float | None
    avg_power_w: float | None
    intensity_type: str | None


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    zone: int
    seconds: float
    low_boundary: float | None


class SetValues(BaseModel):
    exercise_category: str | None = Field(default=None, max_length=64)
    exercise_name: str | None = Field(default=None, max_length=64)
    reps: int | None = Field(default=None, ge=0, le=1000)
    weight_kg: float | None = Field(default=None, ge=0, le=1000)


class SetIn(SetValues):
    deleted: bool = False


class SetOut(SetValues):
    set_index: int
    duration_s: float | None
    original: SetValues
    edited: bool
    deleted: bool


class PlannedMatchOut(BaseModel):
    session_id: int
    title: str
    compliance: float | None
    details: dict[str, list[float]]


class RatingIn(BaseModel):
    effort: int | None = Field(default=None, ge=1, le=10)
    legs: int | None = Field(default=None, ge=1, le=5)
    pain: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=1000)


class RatingOut(RatingIn):
    model_config = ConfigDict(from_attributes=True)


class FuelIn(BaseModel):
    carbs_g: float | None = Field(default=None, ge=0, le=5000)
    fluid_ml: float | None = Field(default=None, ge=0, le=50000)
    gut: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=1000)


class FuelOut(FuelIn):
    model_config = ConfigDict(from_attributes=True)


class ActivityDetailOut(ActivityOut):
    moving_s: float | None
    elevation_loss_m: float | None
    max_hr: float | None
    avg_speed_mps: float | None
    avg_grade_adjusted_speed_mps: float | None
    avg_power_w: float | None
    calories: float | None
    aerobic_training_effect: float | None
    anaerobic_training_effect: float | None
    training_effect_label: str | None
    location_name: str | None
    temperature_c: float | None
    feels_like_c: float | None
    humidity_pct: float | None
    laps: list[LapOut]
    zones: list[ZoneOut]
    sets: list[SetOut]
    planned: PlannedMatchOut | None
    rating: RatingOut | None
    fuel: FuelOut | None
    exercise_categories: list[str]
    drift_first_hr: float | None
    drift_second_hr: float | None
    hr_drift_pct: float | None
    decoupling_pct: float | None


def find_activity(session: SessionDep, activity_id: int) -> Activity:
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise HTTPException(404, "Activity not found")
    return activity


def set_values(row: StrengthSet | StrengthSetOverride) -> SetValues:
    return SetValues(
        exercise_category=row.exercise_category,
        exercise_name=row.exercise_name,
        reps=row.reps,
        weight_kg=row.weight_kg,
    )


def strength_sets(session: SessionDep, activity_id: int) -> list[SetOut]:
    overrides = {
        o.set_index: o
        for o in session.scalars(
            select(StrengthSetOverride).where(StrengthSetOverride.activity_id == activity_id)
        )
    }
    rows = session.scalars(
        select(StrengthSet)
        .where(StrengthSet.activity_id == activity_id, StrengthSet.set_type == "ACTIVE")
        .order_by(StrengthSet.set_index)
    )
    sets = []
    for row in rows:
        override = overrides.get(row.set_index)
        current = set_values(override or row)
        sets.append(
            SetOut(
                **current.model_dump(),
                set_index=row.set_index,
                duration_s=row.duration_s,
                original=set_values(row),
                edited=override is not None,
                deleted=bool(override and override.deleted),
            )
        )
    return sets


def planned_match(session: SessionDep, activity_id: int) -> PlannedMatchOut | None:
    match = session.scalars(
        select(SessionMatch).where(SessionMatch.activity_id == activity_id)
    ).first()
    if match is None:
        return None
    planned = session.get(PlannedSession, match.planned_session_id)
    if planned is None:
        return None
    return PlannedMatchOut(
        session_id=planned.id,
        title=planned.title,
        compliance=match.compliance,
        details=json.loads(match.details),
    )


def own_zones(session: SessionDep, activity_id: int) -> list[ZoneOut]:
    zones = current_zones(session)
    if zones is None:
        return []
    seconds = activity_zone_seconds(session, activity_id, zones)
    if sum(seconds) == 0:
        return []
    return [
        ZoneOut(kind="own", zone=zone.number, seconds=total, low_boundary=zone.low)
        for zone, total in zip(zones, seconds, strict=True)
    ]


@router.get("/activities/{activity_id}", response_model=ActivityDetailOut)
def get_activity(session: SessionDep, activity_id: int) -> ActivityDetailOut:
    activity = find_activity(session, activity_id)
    summary = activity_out(activity, sport_groups(session))
    laps = session.scalars(
        select(ActivityLap)
        .where(ActivityLap.activity_id == activity_id)
        .order_by(ActivityLap.lap_index)
    )
    zones = session.scalars(
        select(ActivityZoneTime)
        .where(ActivityZoneTime.activity_id == activity_id)
        .order_by(ActivityZoneTime.kind, ActivityZoneTime.zone)
    )
    return ActivityDetailOut(
        **summary.model_dump(),
        moving_s=activity.moving_s,
        elevation_loss_m=activity.elevation_loss_m,
        max_hr=activity.max_hr,
        temperature_c=activity.temperature_c,
        feels_like_c=activity.feels_like_c,
        humidity_pct=activity.humidity_pct,
        avg_speed_mps=activity.avg_speed_mps,
        avg_grade_adjusted_speed_mps=activity.avg_grade_adjusted_speed_mps,
        avg_power_w=activity.avg_power_w,
        calories=activity.calories,
        aerobic_training_effect=activity.aerobic_training_effect,
        anaerobic_training_effect=activity.anaerobic_training_effect,
        training_effect_label=activity.training_effect_label,
        location_name=activity.location_name,
        laps=[LapOut.model_validate(lap) for lap in laps],
        zones=[ZoneOut.model_validate(zone) for zone in zones] + own_zones(session, activity_id),
        sets=strength_sets(session, activity_id),
        planned=planned_match(session, activity_id),
        rating=rating_out(session.get(ActivityRating, activity_id)),
        fuel=fuel_out(session.get(ActivityFuel, activity_id)),
        exercise_categories=sorted(MUSCLES_BY_CATEGORY),
        drift_first_hr=activity.drift_first_hr,
        drift_second_hr=activity.drift_second_hr,
        hr_drift_pct=activity.hr_drift_pct,
        decoupling_pct=activity.decoupling_pct,
    )


def rating_out(rating: ActivityRating | None) -> RatingOut | None:
    return None if rating is None else RatingOut.model_validate(rating)


def rating_for(session: SessionDep, activity_id: int) -> ActivityRating:
    find_activity(session, activity_id)
    rating = session.get(ActivityRating, activity_id) or ActivityRating(activity_id=activity_id)
    rating.updated_at = datetime.now()
    session.add(rating)
    return rating


@router.put("/activities/{activity_id}/rating", response_model=RatingOut)
def rate_activity(session: SessionDep, activity_id: int, body: RatingIn) -> ActivityRating:
    rating = rating_for(session, activity_id)
    for field, value in body.model_dump().items():
        setattr(rating, field, value or None)
    session.commit()
    return rating


def fuel_out(fuel: ActivityFuel | None) -> FuelOut | None:
    return None if fuel is None else FuelOut.model_validate(fuel)


@router.put("/activities/{activity_id}/fuel", response_model=FuelOut)
def log_fuel(session: SessionDep, activity_id: int, body: FuelIn) -> ActivityFuel:
    find_activity(session, activity_id)
    fuel = session.get(ActivityFuel, activity_id) or ActivityFuel(activity_id=activity_id)
    fuel.updated_at = datetime.now()
    fuel.carbs_g = body.carbs_g
    fuel.fluid_ml = body.fluid_ml
    fuel.gut = body.gut or None
    fuel.note = body.note or None
    session.add(fuel)
    session.commit()
    return fuel


@router.post("/activities/{activity_id}/effort/{effort}", response_model=RatingOut)
def rate_effort(
    session: SessionDep, activity_id: int, effort: Annotated[int, Path(ge=1, le=10)]
) -> ActivityRating:
    rating = rating_for(session, activity_id)
    rating.effort = effort
    session.commit()
    return rating


def find_set(session: SessionDep, activity_id: int, set_index: int) -> StrengthSet:
    row = session.get(StrengthSet, (activity_id, set_index))
    if row is None:
        raise HTTPException(404, "Strength set not found")
    return row


@router.put("/activities/{activity_id}/sets/{set_index}", response_model=list[SetOut])
def edit_set(session: SessionDep, activity_id: int, set_index: int, body: SetIn) -> list[SetOut]:
    find_set(session, activity_id, set_index)
    override = session.get(StrengthSetOverride, (activity_id, set_index)) or StrengthSetOverride(
        activity_id=activity_id, set_index=set_index
    )
    for field, value in body.model_dump().items():
        setattr(override, field, value)
    override.updated_at = datetime.now()
    session.add(override)
    session.commit()
    return strength_sets(session, activity_id)


@router.delete("/activities/{activity_id}/sets/{set_index}/edit", status_code=204)
def restore_set(session: SessionDep, activity_id: int, set_index: int) -> Response:
    override = session.get(StrengthSetOverride, (activity_id, set_index))
    if override is not None:
        session.delete(override)
        session.commit()
    return Response(status_code=204)
