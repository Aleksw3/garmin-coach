from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Self

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from garmin_coach.api.routes import SessionDep
from garmin_coach.metrics.zones import hr_zones, latest_test, weekly_zone_seconds
from garmin_coach.models import Activity, ThresholdTest
from garmin_coach.normalize.sports import OTHER, sport_groups
from garmin_coach.reports import week_start

router = APIRouter(prefix="/api/zones")

RUNNING_GROUPS = ("run", "vertical")


class TestIn(BaseModel):
    day: date
    lt1_hr: int = Field(ge=80, le=220)
    lt2_hr: int = Field(ge=80, le=230)
    method: Literal["drift_test", "lab", "time_trial", "estimate"]
    activity_id: int | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if self.lt2_hr <= self.lt1_hr:
            raise ValueError("LT2 must be above LT1")
        return self


class TestOut(TestIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ZoneOut(BaseModel):
    number: int
    name: str
    low: int | None
    high: int | None


class ZonesOut(BaseModel):
    current: TestOut | None
    zones: list[ZoneOut]
    tests: list[TestOut]


class ZoneWeekOut(BaseModel):
    week_start: date
    seconds: list[float]


def zones_out(session: SessionDep) -> ZonesOut:
    current = latest_test(session)
    tests = session.scalars(
        select(ThresholdTest).order_by(ThresholdTest.day.desc(), ThresholdTest.id.desc())
    )
    return ZonesOut(
        current=None if current is None else TestOut.model_validate(current),
        zones=[]
        if current is None
        else [ZoneOut(**vars(zone)) for zone in hr_zones(current.lt1_hr, current.lt2_hr)],
        tests=[TestOut.model_validate(test) for test in tests],
    )


@router.get("", response_model=ZonesOut)
def get_zones(session: SessionDep) -> ZonesOut:
    return zones_out(session)


@router.post("/tests", response_model=ZonesOut)
def add_test(session: SessionDep, body: TestIn) -> ZonesOut:
    session.add(ThresholdTest(**body.model_dump(), created_at=datetime.now()))
    session.commit()
    return zones_out(session)


@router.delete("/tests/{test_id}", status_code=204)
def delete_test(session: SessionDep, test_id: int) -> Response:
    test = session.get(ThresholdTest, test_id)
    if test is None:
        raise HTTPException(404, "Test not found")
    session.delete(test)
    session.commit()
    return Response(status_code=204)


@router.get("/weekly", response_model=list[ZoneWeekOut])
def weekly(
    session: SessionDep,
    weeks: Annotated[int, Query(ge=1, le=104)] = 12,
    sports: Literal["running", "all"] = "running",
) -> list[ZoneWeekOut]:
    test = latest_test(session)
    if test is None:
        return []
    zones = hr_zones(test.lt1_hr, test.lt2_hr)
    last_week = week_start(date.today())
    first = last_week - timedelta(weeks=weeks - 1)
    groups = sport_groups(session)
    activities = session.scalars(select(Activity).where(Activity.local_date >= first))
    ids = [
        a.id
        for a in activities
        if not a.is_commute and (sports == "all" or groups.get(a.type_key, OTHER) in RUNNING_GROUPS)
    ]
    by_week = weekly_zone_seconds(session, first, date.today(), ids, zones)
    return [
        ZoneWeekOut(
            week_start=first + timedelta(weeks=index),
            seconds=by_week.get(first + timedelta(weeks=index), [0.0] * len(zones)),
        )
        for index in range(weeks)
    ]
