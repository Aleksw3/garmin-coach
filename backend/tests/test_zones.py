from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.coach.tools import ToolContext, run_tool
from garmin_coach.config import Settings
from garmin_coach.metrics.heart_rate import drift, samples
from garmin_coach.metrics.zones import hr_zones, zone_of, zone_range, zones_line
from garmin_coach.models import ThresholdTest
from garmin_coach.normalize import rebuild_all
from garmin_coach.reports import week_start
from garmin_coach.sync import SyncService
from tests.apps import single_app
from tests.garmin_data import FakeGarmin, activity_summary

STEP_S = 10


def details(heart_rates: list[float], speed: float = 3.0) -> dict[str, object]:
    return {
        "metricDescriptors": [
            {"metricsIndex": 0, "key": "sumDuration"},
            {"metricsIndex": 1, "key": "directHeartRate"},
            {"metricsIndex": 2, "key": "directSpeed"},
        ],
        "activityDetailMetrics": [
            {"metrics": [float(index * STEP_S), hr, speed]} for index, hr in enumerate(heart_rates)
        ],
    }


def steady_run(warmup_hr: float, first_hr: float, second_hr: float) -> list[float]:
    warmup = [warmup_hr] * (15 * 60 // STEP_S)
    half = 30 * 60 // STEP_S
    return warmup + [first_hr] * half + [second_hr] * half + [second_hr]


def test_zones_from_thresholds() -> None:
    zones = hr_zones(144, 165)

    assert [zone_range(zone) for zone in zones] == [
        "under 130",
        "130-144",
        "145-165",
        "166-173",
        "174 and up",
    ]
    assert [zone_of(bpm, zones) for bpm in (100, 130, 144, 145, 166, 190)] == [1, 2, 2, 3, 4, 5]


def test_drift_skips_the_warm_up() -> None:
    result = drift(samples(details(steady_run(110, 140, 144.2))))

    assert result is not None
    assert result.first_half_hr == 140
    assert round(result.drift_pct, 1) == 3.0
    assert result.decoupling_pct is not None and round(result.decoupling_pct, 1) == 2.9
    assert drift(samples(details([140.0] * 200))) is None


def test_zone_api_and_tools(sessions: sessionmaker[Session]) -> None:
    today = date.today()
    with sessions() as session:
        start = f"{today - timedelta(days=1)} 07:00:00"
        raw_store.put_activity(session, 1, "summary", activity_summary(1, start, duration_s=4500))
        raw_store.put_activity(session, 1, "details", details(steady_run(110, 140, 150)))
        rebuild_all(session)
        session.commit()

    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), sessions, request_delay=0, sleep=lambda _: None)

    coach = Coach(sessions, None, coach_settings(Settings.model_construct()))
    client = TestClient(single_app(sessions, make_service, coach, schedule_sync=False))

    assert client.get("/api/zones").json()["current"] is None
    assert client.get("/api/zones/weekly").json() == []
    bad = {"day": str(today), "lt1_hr": 160, "lt2_hr": 150, "method": "estimate"}
    assert client.post("/api/zones/tests", json=bad).status_code == 422
    test = {"day": str(today), "lt1_hr": 144, "lt2_hr": 165, "method": "drift_test"}
    zones = client.post("/api/zones/tests", json=test).json()
    assert [zone["low"] for zone in zones["zones"]] == [None, 130, 145, 166, 174]

    weeks = client.get("/api/zones/weekly", params={"weeks": 2}).json()
    by_week = {week["week_start"]: week["seconds"] for week in weeks}
    seconds = by_week[str(week_start(today - timedelta(days=1)))]
    assert [round(total / 60) for total in seconds] == [15, 30, 30, 0, 0]

    detail = client.get("/api/activities/1").json()
    own = [zone["seconds"] for zone in detail["zones"] if zone["kind"] == "own"]
    assert [round(total / 60) for total in own] == [15, 30, 30, 0, 0]
    assert round(detail["hr_drift_pct"], 1) == 7.1

    with sessions() as session:
        context = ToolContext(session, datetime.now(), 1.92)
        output, ok = run_tool(
            context, "get_zone_time", {"start": str(today - timedelta(days=7)), "end": str(today)}
        )
        activity, _ = run_tool(context, "get_activity", {"activity_id": 1})
    assert ok
    assert "Z2 130-144" in output
    assert "15 / 30 / 30 / 0 / 0" in output
    assert "drift 7.1%" in activity


def test_zones_line_asks_for_a_new_test_after_8_weeks(session: Session) -> None:
    tested = date(2026, 9, 1)
    session.add(
        ThresholdTest(
            day=tested, lt1_hr=150, lt2_hr=170, method="drift_test", created_at=datetime.now()
        )
    )
    session.flush()
    fresh = zones_line(session, tested + timedelta(days=56))
    stale = zones_line(session, tested + timedelta(days=57))
    assert fresh is not None and "test is due" not in fresh
    assert stale is not None
    assert "57 days old, more than 8 weeks, so a new LT1 and LT2 test is due" in stale
