from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from garmin_coach.api.profile import SessionDep
from garmin_coach.course import MAX_GPX_BYTES, CourseError, as_json, describe, save_course
from garmin_coach.metrics.projection import Projection, project
from garmin_coach.models import Goal, GoalCourse

router = APIRouter(prefix="/api")


def find_goal(session: SessionDep, goal_id: int) -> Goal:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="No such goal")
    return goal


@router.get("/goals/{goal_id}/course")
def get_course(session: SessionDep, goal_id: int) -> dict[str, Any] | None:
    find_goal(session, goal_id)
    row = session.get(GoalCourse, goal_id)
    return as_json(describe(row)) if row else None


@router.put("/goals/{goal_id}/course")
async def put_course(session: SessionDep, goal_id: int, request: Request) -> dict[str, Any]:
    goal = find_goal(session, goal_id)
    content = await request.body()
    if len(content) > MAX_GPX_BYTES:
        raise HTTPException(status_code=413, detail="The GPX file is too large")
    try:
        row = save_course(session, goal, content)
    except CourseError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return as_json(describe(row))


class ArrivalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    km: float
    fast_s: float
    slow_s: float


class ReferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    activity_id: int
    day: date
    name: str | None
    distance_km: float
    gain_m: float
    seconds: float


class ProjectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    distance_km: float
    gain_m: float
    effort_km: float
    fast_s: float
    slow_s: float
    references: list[ReferenceOut]
    arrivals: list[ArrivalOut]


@router.get("/goals/{goal_id}/projection", response_model=ProjectionOut | None)
def get_projection(session: SessionDep, goal_id: int) -> Projection | None:
    return project(session, find_goal(session, goal_id), date.today())


@router.delete("/goals/{goal_id}/course", status_code=204)
def delete_course(session: SessionDep, goal_id: int) -> Response:
    row = session.get(GoalCourse, goal_id)
    if row is not None:
        session.delete(row)
        session.commit()
    return Response(status_code=204)
