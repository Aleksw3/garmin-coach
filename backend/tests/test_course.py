import math
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.coach.tools import ToolContext, run_tool
from garmin_coach.config import Settings
from garmin_coach.course import CourseError, describe, parse_gpx, save_course
from garmin_coach.metrics.progress import progress, target_seconds
from garmin_coach.metrics.projection import project
from garmin_coach.models import Activity, ActivityFuel, Climb, Goal, GoalCourse
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


def long_run(
    session: Session, activity_id: int, day: date, km: float, gain: float, hours: float
) -> None:
    session.add(
        Activity(
            id=activity_id,
            name=f"Long run {activity_id}",
            type_key="trail_running",
            start_time_local=datetime(day.year, day.month, day.day, 8),
            start_time_gmt=datetime(day.year, day.month, day.day, 7),
            local_date=day,
            duration_s=hours * 3600,
            distance_m=km * 1000,
            elevation_gain_m=gain,
        )
    )


def test_projection_scales_a_long_run_to_the_race(session: Session) -> None:
    today = date(2026, 11, 10)
    goal = Goal(kind="race", title="Race", distance_km=60, elevation_gain_m=3000)
    session.add(goal)
    long_run(session, 1, date(2026, 10, 1), km=30, gain=1500, hours=4.5)
    long_run(session, 2, date(2025, 10, 1), km=30, gain=1500, hours=3.0)
    session.flush()
    projection = project(session, goal, today)
    assert projection is not None
    assert projection.effort_km == 90
    assert [r.activity_id for r in projection.references] == [1]
    assert projection.fast_s == pytest.approx(4.5 * 3600 * 2**1.06)
    assert projection.slow_s == pytest.approx(4.5 * 3600 * 2**1.15)
    assert projection.arrivals == []


def test_projection_gives_arrivals_along_the_course(session: Session) -> None:
    row = stored(session, gpx())
    goal = session.get(Goal, row.goal_id)
    assert goal is not None
    long_run(session, 1, date(2026, 10, 1), km=15, gain=500, hours=2.0)
    session.flush()
    projection = project(session, goal, date(2026, 11, 10))
    assert projection is not None
    summit, finish = projection.arrivals
    assert summit.name == "Summit hut"
    assert summit.fast_s == pytest.approx(projection.fast_s * 18 / 30, rel=0.02)
    assert finish.slow_s == pytest.approx(projection.slow_s)
    ctx = ToolContext(session=session, now=datetime(2026, 11, 10, 12), trimp_coefficient=1.92)
    text, ok = run_tool(ctx, "get_race_projection", {})
    assert ok
    assert "Finish estimate" in text
    assert "Summit hut at km 12.0" in text


def test_no_projection_without_long_runs(session: Session) -> None:
    goal = Goal(kind="race", title="Race", distance_km=60)
    session.add(goal)
    session.flush()
    assert project(session, goal, date(2026, 11, 10)) is None


@pytest.mark.parametrize(
    ("target", "seconds"),
    [("under 5 hours", 18000), ("sub 4:30", 16200), ("4,5 h", 16200), ("finish", None)],
)
def test_target_time_is_read_from_the_goal_text(target: str, seconds: float | None) -> None:
    assert target_seconds(target) == seconds


def test_progress_compares_now_with_12_weeks_ago(session: Session) -> None:
    today = date(2026, 11, 10)
    row = stored(session, gpx())
    goal = session.get(Goal, row.goal_id)
    assert goal is not None
    goal.target = "under 2 hours"
    long_run(session, 1, date(2026, 7, 20), km=10, gain=200, hours=1.5)
    long_run(session, 2, date(2026, 11, 1), km=20, gain=1000, hours=3.0)
    session.add(ActivityFuel(activity_id=2, carbs_g=150, updated_at=datetime(2026, 11, 1)))
    session.add_all(
        Climb(
            activity_id=2,
            start_lat=60,
            start_lon=10,
            length_m=2000,
            gain_m=gain,
            seconds=1200,
            track=[],
        )
        for gain in (200, 200, 240, 240)
    )
    session.flush()
    found = progress(session, goal, today)
    parts = {part.key: part for part in found.parts}

    assert found.target_s == 2 * 3600
    assert found.estimates[-1].day == today
    assert found.estimates[-1].fast_s < found.estimates[0].fast_s
    assert parts["longest"].now == 30
    assert parts["longest"].before == 12
    assert parts["longest"].race == pytest.approx(30, rel=0.02)
    assert parts["volume"].now == pytest.approx(5)
    assert parts["descent"].race == pytest.approx(600, rel=0.02)
    assert parts["climb_rate"].now == pytest.approx(720)
    assert parts["climb_rate"].before is None
    assert parts["fueling"].now == pytest.approx(50)
    assert parts["durability"].now is None
    needed = found.seconds_per_week_needed
    assert needed is not None and needed > 0

    ctx = ToolContext(session=session, now=datetime(2026, 11, 10, 12), trimp_coefficient=1.92)
    text, ok = run_tool(ctx, "get_goal_progress", {})
    assert ok
    assert (
        "Longest day: now 30 effort-km, 12 weeks ago 12 effort-km, the race has 30 effort-km"
        in text
    )
    assert "Target time 2 h 00 min" in text

    flat = session.get(Activity, 1)
    hilly = session.get(Activity, 2)
    assert flat is not None and hilly is not None
    flat.elevation_gain_m, flat.decoupling_pct = 50, 6.0
    hilly.decoupling_pct = -20.0
    session.flush()
    assert {p.key: p for p in progress(session, goal, today).parts}["durability"].before == 6.0


def test_progress_over_the_api(sessions: sessionmaker[Session]) -> None:
    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), sessions, request_delay=0, sleep=lambda _: None)

    coach = Coach(sessions, None, coach_settings(Settings.model_construct()))
    client = TestClient(single_app(sessions, make_service, coach))
    goal = {"kind": "race", "title": "Race", "distance_km": 60, "target": "5:30"}
    goal_id = client.post("/api/goals", json=goal).json()["id"]
    body = client.get(f"/api/goals/{goal_id}/progress").json()
    assert body["target_s"] == 19800
    assert body["estimates"] == []
    assert [part["key"] for part in body["parts"]][:2] == ["volume", "longest"]
    assert body["parts"][1]["race"] == 60
