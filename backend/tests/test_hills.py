from datetime import date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.coach.tools import ToolContext, run_tool
from garmin_coach.config import Settings
from garmin_coach.metrics.hills import (
    DEFAULT_FLAT_SPEED_MPS,
    find_hills,
    home_point,
    uphill_speed,
)
from garmin_coach.models import Activity, Climb
from garmin_coach.normalize import normalize_activity
from garmin_coach.normalize.climbs import scan_missing_climbs
from garmin_coach.sync import SyncService
from tests.apps import single_app
from tests.garmin_data import FakeGarmin, activity_summary

TODAY = date(2026, 11, 4)
START = (59.0, 5.5)
METERS_PER_DEGREE = 111_195.0
FIELDS = ["sumDistance", "directElevation", "directLatitude", "directLongitude", "sumDuration"]


def elevation_at(distance: float) -> float:
    if distance < 500:
        return 10.0
    if distance < 1500:
        return 10.0 + 0.08 * (distance - 500)
    return 90.0 - 0.08 * min(distance - 1500, 1000)


def details(length_m: float = 3000.0, east_m: float = 0.0) -> dict[str, Any]:
    rows = []
    seconds = 0.0
    for step in range(int(length_m / 10) + 1):
        distance = step * 10.0
        lat = START[0] + distance / METERS_PER_DEGREE
        lon = START[1] + east_m / (METERS_PER_DEGREE * 0.515)
        rows.append({"metrics": [distance, elevation_at(distance), lat, lon, seconds]})
        seconds += 10 / 2.5
    return {
        "metricDescriptors": [{"key": key, "metricsIndex": i} for i, key in enumerate(FIELDS)],
        "activityDetailMetrics": rows,
    }


def add_activity(
    session: Session,
    activity_id: int,
    start: str,
    type_key: str = "running",
    track: dict[str, Any] | None = None,
) -> None:
    raw_store.put_activity(
        session, activity_id, "summary", activity_summary(activity_id, start, type_key=type_key)
    )
    raw_store.put_activity(session, activity_id, "details", track or details())
    normalize_activity(session, activity_id)
    session.flush()


def test_normalize_finds_the_climb(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00")

    climb = session.scalars(select(Climb)).one()
    assert climb.gain_m == pytest.approx(80, abs=4)
    assert climb.length_m == pytest.approx(1000, abs=60)
    assert climb.start_lat == pytest.approx(START[0] + 500 / METERS_PER_DEGREE, abs=1e-3)
    assert session.scalars(select(Activity.climbs_scanned)).one()


def test_strength_and_ski_activities_get_no_climbs(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00", type_key="strength_training")
    add_activity(session, 2, "2026-10-21 07:00:00", type_key="backcountry_skiing")

    assert session.scalars(select(Climb)).all() == []
    assert all(a.climbs_scanned for a in session.scalars(select(Activity)))


def test_scan_fills_activities_from_before_the_climb_table(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00")
    session.execute(delete(Climb))
    session.execute(update(Activity).values(climbs_scanned=False))

    assert scan_missing_climbs(session) == 1
    assert len(session.scalars(select(Climb)).all()) == 1
    assert scan_missing_climbs(session) == 0


def test_hill_section_matches_the_repeat_time(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00")
    add_activity(session, 2, "2026-10-27 07:00:00")

    result = find_hills(session, TODAY, 8, 2, rep_minutes=3)

    hill = result.hills[0]
    assert not result.effort.from_data
    expected_m = uphill_speed(DEFAULT_FLAT_SPEED_MPS, 0.08) * 180
    assert hill.length_m == pytest.approx(expected_m, abs=40)
    assert hill.grade == pytest.approx(0.08, abs=0.01)
    assert hill.rep_seconds == pytest.approx(180, abs=15)
    assert hill.visits == 2
    assert hill.last_day == date(2026, 10, 27)
    assert len(result.hills) == 1
    assert "travelmode=walking" in hill.map_url()


def test_repeat_length_in_meters(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00")

    hill = find_hills(session, TODAY, 8, 2, rep_meters=300).hills[0]

    assert hill.length_m == pytest.approx(300, abs=20)


def test_no_hill_when_the_gradient_does_not_fit(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00")

    assert find_hills(session, TODAY, 15, 2, rep_minutes=3).hills == []


def test_hill_longer_than_any_climb_is_not_suggested(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00")

    assert find_hills(session, TODAY, 8, 2, rep_minutes=10).hills == []


def test_separate_roads_are_separate_hills(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00")
    add_activity(session, 2, "2026-10-21 07:00:00", track=details(east_m=400))

    assert len(find_hills(session, TODAY, 8, 2, rep_minutes=3).hills) == 2


def test_home_is_the_most_common_recent_start(session: Session) -> None:
    for index in range(3):
        session.add(old_home_activity(index))
    add_activity(session, 10, "2026-10-20 07:00:00")
    add_activity(session, 11, "2026-10-22 07:00:00")

    assert home_point(session, TODAY) == pytest.approx(START)


def old_home_activity(index: int) -> Activity:
    start = datetime(2025, 1, 10 + index, 7)
    return Activity(
        id=100 + index,
        type_key="running",
        start_time_local=start,
        start_time_gmt=start,
        local_date=start.date(),
        start_lat=61.0,
        start_lon=7.0,
        climbs_scanned=True,
    )


def test_tool_lists_hills_with_map_links(session: Session) -> None:
    add_activity(session, 1, "2026-10-20 07:00:00")
    ctx = ToolContext(session, datetime(2026, 11, 4, 12), 1.92)

    text, ok = run_tool(ctx, "get_hills", {"rep_minutes": 3, "grade_pct": 8})

    assert ok
    assert "about 3:0" in text
    assert "https://www.google.com/maps/dir/" in text
    assert "a default because there are too few run climbs" in text


def test_tool_needs_one_repeat_length(session: Session) -> None:
    ctx = ToolContext(session, datetime(2026, 11, 4, 12), 1.92)

    text, ok = run_tool(ctx, "get_hills", {"grade_pct": 8})

    assert not ok
    assert "either rep_minutes or rep_meters" in text


@pytest.fixture
def client(sessions: sessionmaker[Session]) -> TestClient:
    with sessions() as session:
        add_activity(session, 1, "2026-10-20 07:00:00")
        session.commit()

    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), sessions, request_delay=0, sleep=lambda _: None)

    coach = Coach(sessions, None, coach_settings(Settings.model_construct()))
    return TestClient(single_app(sessions, make_service, coach))


def test_hills_endpoint(client: TestClient) -> None:
    response = client.get("/api/hills", params={"minutes": 3, "grade": 8})

    assert response.status_code == 200
    body = response.json()
    assert body["speed_from_data"] is False
    hill = body["hills"][0]
    assert hill["grade_pct"] == pytest.approx(8, abs=1)
    assert hill["map_url"].startswith("https://www.google.com/maps/dir/")


def test_hills_endpoint_needs_one_repeat_length(client: TestClient) -> None:
    assert client.get("/api/hills", params={"grade": 8}).status_code == 422
    assert client.get("/api/hills", params={"minutes": 3, "meters": 400}).status_code == 422
