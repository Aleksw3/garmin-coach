import math
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.api.schemas import (
    ActivityOut,
    BaselineOut,
    GroupTotalsOut,
    HrvPointOut,
    LoadOut,
    OneRepMaxOut,
    RunWeekOut,
    StrengthWeekOut,
    SyncRunOut,
    SyncStatusOut,
    TodayOut,
    TrendsOut,
    WellnessOut,
)
from garmin_coach.config import get_settings
from garmin_coach.jobs import SyncRunner
from garmin_coach.metrics.load import training_load
from garmin_coach.metrics.recovery import BaselineStatus, hrv_baseline, resting_hr_baseline
from garmin_coach.metrics.running import climb_per_km, run_weeks, terrain
from garmin_coach.metrics.strength import best_one_rep_max, effective_sets, weekly_sets_per_muscle
from garmin_coach.models import Activity, DailyWellness, SyncRun
from garmin_coach.normalize.sports import OTHER, sport_groups
from garmin_coach.reports import WeekTotals, week_start, weekly_totals
from garmin_coach.sync import LAST_SYNC, get_state

router = APIRouter(prefix="/api")

RECENT_ACTIVITY_COUNT = 5
TERRAIN_GROUPS = ("run", "vertical")


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_runner(request: Request) -> SyncRunner:
    runner: SyncRunner = request.app.state.sync_runner
    return runner


def group_totals(rows: list[WeekTotals]) -> list[GroupTotalsOut]:
    return [GroupTotalsOut(**vars(row)) for row in rows]


def baseline_out(status: BaselineStatus | None, as_ms: bool = False) -> BaselineOut | None:
    if status is None:
        return None
    convert = math.exp if as_ms else float
    return BaselineOut(
        day=status.day,
        rolling=convert(status.rolling),
        low=convert(status.low),
        high=convert(status.high),
        status=status.status,
    )


def activity_out(activity: Activity, groups: dict[str, str]) -> ActivityOut:
    group = groups.get(activity.type_key, OTHER)
    climb = climb_per_km(activity.elevation_gain_m, activity.distance_m)
    return ActivityOut(
        id=activity.id,
        name=activity.name,
        type_key=activity.type_key,
        sport_group="commute" if activity.is_commute else group,
        start_time_local=activity.start_time_local,
        duration_s=activity.duration_s,
        distance_km=None if activity.distance_m is None else activity.distance_m / 1000,
        elevation_gain_m=activity.elevation_gain_m,
        avg_hr=activity.avg_hr,
        training_load=activity.training_load,
        terrain=terrain(climb) if group in TERRAIN_GROUPS else None,
        is_commute=activity.is_commute,
    )


def latest_wellness(session: Session, day: date) -> WellnessOut | None:
    latest = (
        select(DailyWellness).where(DailyWellness.day <= day).order_by(DailyWellness.day.desc())
    )
    wellness = session.scalars(latest.limit(1)).first()
    if wellness is None:
        return None
    slept = session.scalars(latest.where(DailyWellness.sleep_s.is_not(None)).limit(1)).first()
    return WellnessOut(
        day=wellness.day,
        sleep_day=slept.day if slept else None,
        sleep_h=slept.sleep_s / 3600 if slept and slept.sleep_s else None,
        sleep_score=slept.sleep_score if slept else None,
        hrv_last_night=wellness.hrv_last_night,
        hrv_status=wellness.hrv_status,
        resting_hr=wellness.resting_hr,
        readiness_score=wellness.readiness_score,
        readiness_level=wellness.readiness_level,
        training_status=wellness.training_status,
        body_battery_at_wake=wellness.body_battery_at_wake,
    )


@router.get("/today", response_model=TodayOut)
def today(session: SessionDep, day: date | None = None) -> TodayOut:
    day = day or date.today()
    groups = sport_groups(session)
    load = training_load(session, day, day, get_settings().trimp_coefficient)
    hrv = hrv_baseline(session, day, day)
    recent = session.scalars(
        select(Activity)
        .where(Activity.local_date <= day)
        .order_by(Activity.start_time_local.desc())
        .limit(RECENT_ACTIVITY_COUNT)
    )
    this_week = week_start(day)
    return TodayOut(
        day=day,
        wellness=latest_wellness(session, day),
        hrv=baseline_out(hrv[-1] if hrv else None, as_ms=True),
        resting_hr=baseline_out(resting_hr_baseline(session, day)),
        load=LoadOut(**vars(load[-1])) if load else None,
        week=group_totals(weekly_totals(session, this_week, this_week)),
        recent_activities=[activity_out(a, groups) for a in recent],
    )


def hrv_points(session: Session, first: date, last: date) -> list[HrvPointOut]:
    statuses = {s.day: s for s in hrv_baseline(session, first, last)}
    rows = session.execute(
        select(DailyWellness.day, DailyWellness.hrv_last_night).where(
            DailyWellness.day >= first, DailyWellness.day <= last
        )
    )
    values = {day: value for day, value in rows}
    points = []
    day = first
    while day <= last:
        status = statuses.get(day)
        points.append(
            HrvPointOut(
                day=day,
                value=values.get(day),
                rolling=None if status is None else math.exp(status.rolling),
                low=None if status is None else math.exp(status.low),
                high=None if status is None else math.exp(status.high),
            )
        )
        day += timedelta(days=1)
    return points


@router.get("/trends", response_model=TrendsOut)
def trends(
    session: SessionDep,
    weeks: Annotated[int, Query(ge=1, le=104)] = 12,
    end: date | None = None,
) -> TrendsOut:
    last = end or date.today()
    last_week = week_start(last)
    first_week = last_week - timedelta(weeks=weeks - 1)
    return TrendsOut(
        first_week=first_week,
        last_week=last_week,
        weekly_totals=group_totals(weekly_totals(session, first_week, last_week)),
        load=[
            LoadOut(**vars(entry))
            for entry in training_load(session, first_week, last, get_settings().trimp_coefficient)
        ],
        hrv=hrv_points(session, first_week, last),
        run_weeks=[
            RunWeekOut(
                week_start=week.week_start,
                runs=week.runs,
                distance_km=week.distance_km,
                hours=week.hours,
                elevation_gain_m=week.elevation_gain_m,
                elevation_loss_m=week.elevation_loss_m,
                longest_run_h=week.longest_run_h,
                flat_h=week.hours_by_terrain.get("flat", 0.0),
                rolling_h=week.hours_by_terrain.get("rolling", 0.0),
                mountain_h=week.hours_by_terrain.get("mountain", 0.0),
                back_to_back_long_days=week.back_to_back_long_days,
            )
            for week in run_weeks(session, first_week, last_week)
        ],
        strength_weeks=[
            StrengthWeekOut(week_start=week, sets_per_muscle=muscles)
            for week, muscles in weekly_sets_per_muscle(session, first_week, last_week).items()
        ],
        one_rep_max=[
            OneRepMaxOut(exercise=exercise, day=day, kg=kg)
            for exercise, (day, kg) in sorted(
                best_one_rep_max(effective_sets(session, first_week, last)).items()
            )
        ],
    )


def sync_status(session: Session, runner: SyncRunner) -> SyncStatusOut:
    runs = session.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(5))
    return SyncStatusOut(
        running=runner.running,
        last_sync=get_state(session, LAST_SYNC),
        runs=[SyncRunOut.model_validate(run, from_attributes=True) for run in runs],
    )


@router.get("/sync", response_model=SyncStatusOut)
def get_sync(session: SessionDep, request: Request) -> SyncStatusOut:
    return sync_status(session, get_runner(request))


@router.post("/sync", response_model=SyncStatusOut)
def start_sync(session: SessionDep, request: Request) -> SyncStatusOut:
    runner = get_runner(request)
    runner.start_in_background()
    return sync_status(session, runner)
