from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from garmin_coach.api.profile import SessionDep
from garmin_coach.metrics.hills import find_hills

router = APIRouter(prefix="/api/hills")


class HillOut(BaseModel):
    start: tuple[float, float]
    end: tuple[float, float]
    length_m: float
    gain_m: float
    grade_pct: float
    steepest_pct: float
    rep_seconds: float
    away_m: float
    visits: int
    last_day: date
    map_url: str


class HillsOut(BaseModel):
    flat_speed_mps: float
    speed_from_data: bool
    hills: list[HillOut]


@router.get("", response_model=HillsOut)
def get_hills(
    session: SessionDep,
    minutes: Annotated[float | None, Query(gt=0, le=30)] = None,
    meters: Annotated[float | None, Query(gt=0, le=5000)] = None,
    grade: Annotated[float, Query(ge=2, le=40)] = 8,
    tolerance: Annotated[float, Query(ge=0.5, le=10)] = 2,
    near: Annotated[str | None, Query(max_length=100)] = None,
    max_km: Annotated[float, Query(gt=0, le=100)] = 10,
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
) -> HillsOut:
    if (minutes is None) == (meters is None):
        raise HTTPException(422, "Give either minutes or meters")
    result = find_hills(
        session,
        date.today(),
        grade,
        tolerance,
        rep_minutes=minutes,
        rep_meters=meters,
        near=near,
        max_km=max_km,
        limit=limit,
    )
    return HillsOut(
        flat_speed_mps=result.effort.flat_speed_mps,
        speed_from_data=result.effort.from_data,
        hills=[
            HillOut(
                start=hill.start,
                end=hill.end,
                length_m=hill.length_m,
                gain_m=hill.gain_m,
                grade_pct=100 * hill.grade,
                steepest_pct=100 * hill.steepest_grade,
                rep_seconds=hill.rep_seconds,
                away_m=hill.away_m,
                visits=hill.visits,
                last_day=hill.last_day,
                map_url=hill.map_url(),
            )
            for hill in result.hills
        ],
    )
