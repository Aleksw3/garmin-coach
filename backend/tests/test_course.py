import math
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.coach.tools import ToolContext, run_tool
from garmin_coach.config import Settings
from garmin_coach.course import CourseError, describe, parse_gpx, save_course
from garmin_coach.models import Goal, GoalCourse
from garmin_coach.sync import SyncService
from tests.apps import single_app
from tests.garmin_data import FakeGarmin

METERS_PER_DEGREE = 111_195.0
COURSE_KM = 24
SUMMIT_M = 1100.0
VALLEY_M = 500.0


def elevation(km: float) -> float:
    return VALLEY_M + (SUMMIT_M - VALLEY_M) * math.sin(math.pi * km / COURSE_KM) ** 2


def gpx(waypoints: bool = True) -> bytes:
    points = "".join(
        f'<trkpt lat="{60 + step * 50 / METERS_PER_DEGREE:.6f}" lon="10.0">'
        f"<ele>{elevation(step * 0.05):.1f}</ele></trkpt>"
        for step in range(COURSE_KM * 20 + 1)
    )
    aid = (
        f'<wpt lat="{60 + 12_000 / METERS_PER_DEGREE:.6f}" lon="10.0"><name>Summit hut</name></wpt>'
        '<wpt lat="61.5" lon="10.0"><name>Far away</name></wpt>'
        if waypoints
        else ""
    )
    return (
        '<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">'
        f"{aid}<trk><name>Mountain loop</name><trkseg>{points}</trkseg></trk></gpx>"
    ).encode()


def stored(session: Session, content: bytes) -> GoalCourse:
    goal = Goal(kind="race", title="Mountain race", target_date=date(2027, 8, 1))
    session.add(goal)
    session.flush()
    row = save_course(session, goal, content)
    session.flush()
    return row


def test_course_totals_and_legs_from_gpx(session: Session) -> None:
    course = describe(stored(session, gpx()))
    assert course.name == "Mountain loop"
    assert course.distance_m == pytest.approx(24_000, abs=100)
    assert course.gain_m == pytest.approx(600, abs=10)
    assert course.loss_m == pytest.approx(600, abs=10)
    assert [w.name for w in course.waypoints] == ["Summit hut"]
    assert [leg.name for leg in course.legs] == ["Summit hut", "Finish"]
    assert course.legs[0].end_m == pytest.approx(12_000, abs=100)
    assert course.legs[0].gain_m == pytest.approx(600, abs=10)
    assert course.legs[1].loss_m == pytest.approx(600, abs=10)
    assert len(course.climbs) == 1
    assert course.climbs[0].change_m == pytest.approx(600, abs=15)
    assert course.descents[0].change_m == pytest.approx(-600, abs=15)


def test_course_without_waypoints_has_a_leg_every_10_km(session: Session) -> None:
    course = describe(stored(session, gpx(waypoints=False)))
    assert [leg.name for leg in course.legs] == ["km 10", "km 20", "Finish"]


@pytest.mark.parametrize(
    "content",
    [
        b"not xml",
        b"<gpx></gpx>",
        b'<gpx><trk><trkseg><trkpt lat="1" lon="1"/></trkseg></trk></gpx>',
    ],
)
def test_bad_gpx_is_rejected(content: bytes) -> None:
    with pytest.raises(CourseError):
        parse_gpx(content)


def test_coach_reads_the_course(session: Session) -> None:
    stored(session, gpx())
    ctx = ToolContext(session=session, now=datetime(2026, 11, 10, 12), trimp_coefficient=1.92)
    text, ok = run_tool(ctx, "get_course", {})
    assert ok
    assert "Mountain race" in text
    assert "24.0 km" in text
    assert "to Summit hut at km 12.0" in text
    assert "Long descents" in text
    goals, _ = run_tool(ctx, "get_goals", {})
    assert "course uploaded" in goals


def test_course_upload_and_delete_over_the_api(sessions: sessionmaker[Session]) -> None:
    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), sessions, request_delay=0, sleep=lambda _: None)

    coach = Coach(sessions, None, coach_settings(Settings.model_construct()))
    client = TestClient(single_app(sessions, make_service, coach))
    goal_id = client.post("/api/goals", json={"kind": "race", "title": "Race"}).json()["id"]
    assert client.get(f"/api/goals/{goal_id}/course").json() is None
    assert client.put(f"/api/goals/{goal_id}/course", content=b"nope").status_code == 422
    uploaded = client.put(f"/api/goals/{goal_id}/course", content=gpx()).json()
    assert uploaded["distance_km"] == pytest.approx(24, abs=0.1)
    assert uploaded["waypoints"] == [{"name": "Summit hut", "km": 12.0}]
    assert client.get(f"/api/goals/{goal_id}/course").json()["name"] == "Mountain loop"
    assert client.delete(f"/api/goals/{goal_id}").status_code == 204
    with sessions() as session:
        assert session.get(GoalCourse, goal_id) is None
