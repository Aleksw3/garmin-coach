from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.api.app import create_app
from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.config import Settings
from garmin_coach.normalize import rebuild_all
from garmin_coach.sync import SyncService
from tests.garmin_data import FakeGarmin, activity_summary, daily

DAY = date(2026, 10, 28)


@pytest.fixture
def client(sessions: sessionmaker[Session]) -> TestClient:
    with sessions() as session:
        for offset in range(70):
            day = DAY - timedelta(days=offset)
            for kind in ("stats", "sleep", "hrv"):
                raw_store.put_daily(session, day, kind, daily(kind, day))
        for activity_id, start, type_key in [
            (1, "2026-10-27 07:00:00", "running"),
            (2, "2026-10-26 18:00:00", "strength_training"),
            (3, "2026-10-12 09:00:00", "hiking"),
        ]:
            summary = activity_summary(activity_id, start, type_key=type_key)
            raw_store.put_activity(session, activity_id, "summary", summary)
        rebuild_all(session)
        session.commit()

    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), sessions, request_delay=0, sleep=lambda _: None)

    coach = Coach(sessions, None, coach_settings(Settings.model_construct()))
    return TestClient(create_app(sessions, make_service, coach, schedule_sync=False))


def test_today(client: TestClient) -> None:
    body = client.get("/api/today", params={"day": DAY.isoformat()}).json()

    assert body["day"] == DAY.isoformat()
    assert body["wellness"]["resting_hr"] == 43
    assert body["wellness"]["sleep_h"] == pytest.approx(28740 / 3600)
    assert body["hrv"]["status"] == "within"
    assert body["hrv"]["rolling"] == pytest.approx(64.0)
    assert body["load"]["acute"] > 0
    assert [a["id"] for a in body["recent_activities"]] == [1, 2, 3]
    assert body["recent_activities"][0]["terrain"] == "mountain"
    assert {row["sport_group"] for row in body["week"]} == {"run", "strength"}


def test_trends(client: TestClient) -> None:
    body = client.get("/api/trends", params={"weeks": 4, "end": DAY.isoformat()}).json()

    assert body["first_week"] == "2026-10-05"
    assert body["last_week"] == "2026-10-26"
    assert len(body["run_weeks"]) == 4
    assert len(body["hrv"]) == 24
    assert body["load"][-1]["day"] == DAY.isoformat()
    assert any(row["sport_group"] == "vertical" for row in body["weekly_totals"])


def test_trends_rejects_unreasonable_week_counts(client: TestClient) -> None:
    assert client.get("/api/trends", params={"weeks": 0}).status_code == 422


def test_sync_status_and_trigger(client: TestClient) -> None:
    assert client.get("/api/sync").json()["running"] is False
    assert client.post("/api/sync").status_code == 200
