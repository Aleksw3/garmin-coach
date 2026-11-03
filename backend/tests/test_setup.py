import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.api import setup_routes
from garmin_coach.api.app import create_app
from garmin_coach.claude_settings import InvalidApiKey
from garmin_coach.config import Settings
from garmin_coach.garmin.connect import GarminWebLogin, PendingLogin
from garmin_coach.household import Household
from garmin_coach.profiles import open_research, slug_for
from garmin_coach.sync import SyncService
from tests.garmin_data import FakeGarmin

KEY = "sk-ant-api03-" + "x" * 40 + "abcd"


class FakeLogin(GarminWebLogin):
    def start(self, tokens_dir: Path, email: str, password: str) -> PendingLogin | None:
        if password == "wrong":
            raise ValueError("401 Unauthorized")
        if email.startswith("mfa"):
            return PendingLogin(client=None, state={"email": email})  # type: ignore[arg-type]
        self.save(tokens_dir)
        return None

    def finish(self, pending: PendingLogin, code: str, tokens_dir: Path) -> None:
        if code != "123456":
            raise ValueError("Wrong code")
        self.save(tokens_dir)

    def save(self, tokens_dir: Path) -> None:
        tokens_dir.mkdir(parents=True, exist_ok=True)
        (tokens_dir / "garmin_tokens.json").write_text("{}")


def fake_sync_service(slug: str, sessions: sessionmaker[Session]) -> SyncService:
    return SyncService(FakeGarmin([]), sessions, request_delay=0, sleep=lambda _: None)


@pytest.fixture
def household(tmp_path: Path) -> Household:
    settings = Settings.model_construct(data_dir=tmp_path, trimp_coefficient=1.92)
    return Household(settings, open_research(settings), fake_sync_service)


def client_for(household: Household, **options: Any) -> TestClient:
    app = create_app(
        household.open_all(),
        household.research,
        household=household,
        garmin_login=FakeLogin(),
        **options,
    )
    return TestClient(app)


def test_slug_for_names() -> None:
    assert slug_for("Kari Nordmann", set()) == "kari-nordmann"
    assert slug_for("Åse Ødegård", set()) == "ase-odegard"
    assert slug_for("Kari", {"kari", "kari-2"}) == "kari-3"
    assert slug_for("!!!", set()) == "person"


def test_key_and_budget_apply_to_running_coaches(
    household: Household, monkeypatch: pytest.MonkeyPatch
) -> None:
    def check(key: str) -> None:
        if key.endswith("bad!"):
            raise InvalidApiKey("Anthropic rejected the key")

    monkeypatch.setattr(setup_routes, "check_api_key", check)
    client = client_for(household, schedule_sync=False)
    assert client.get("/api/profiles").json() == []
    assert client.get("/api/claude").json()["key_set"] is False

    kari = client.post("/api/profiles", json={"name": "Kari", "trimp_coefficient": 1.67}).json()
    assert kari == {"slug": "kari", "name": "Kari"}
    coach = household.profiles["kari"].coach
    assert not coach.ready
    assert not household.fetcher.ready

    bad = client.put("/api/claude", json={"api_key": KEY[:-4] + "bad!"})
    assert bad.status_code == 400
    claude = client.put("/api/claude", json={"api_key": KEY, "monthly_budget_usd": 8}).json()
    assert claude == {
        "available": True,
        "key_set": True,
        "key_hint": "abcd",
        "source": "app",
        "monthly_budget_usd": 8.0,
    }
    assert coach.ready
    assert coach.settings.monthly_budget_usd == 8.0
    assert household.fetcher.ready
    usage = client.get("/api/usage", headers={"X-Profile": "kari"}).json()
    assert usage["budget_usd"] == 8.0

    reopened = Household(household.settings, household.research, fake_sync_service)
    assert reopened.claude.key_hint == "abcd"
    assert reopened.claude.monthly_budget_usd == 8.0


def test_garmin_login_with_code_and_backfill(household: Household) -> None:
    with client_for(household) as client:
        client.post("/api/profiles", json={"name": "Kari", "trimp_coefficient": 1.67})
        client.post("/api/profiles", json={"name": "Kari", "trimp_coefficient": 1.67})
        jobs = {job.id for job in client.app.state.scheduler.get_jobs()}  # type: ignore[attr-defined]
        assert {"recent_sync_kari", "recent_sync_kari-2", "morning_checkin_kari-2"} <= jobs

        kari = {"X-Profile": "kari"}
        assert client.get("/api/garmin", headers=kari).json()["connected"] is False
        early = client.post("/api/garmin/backfill", json={"days": 3}, headers=kari)
        assert early.status_code == 409

        login = {"email": "mfa@example.com", "password": "wrong"}
        failed = client.post("/api/garmin/login", json=login, headers=kari)
        assert failed.status_code == 400
        assert "401" in failed.json()["detail"]

        login["password"] = "secret"
        waiting = client.post("/api/garmin/login", json=login, headers=kari).json()
        assert (waiting["waiting_for_code"], waiting["connected"]) == (True, False)
        wrong = client.post("/api/garmin/code", json={"code": "000000"}, headers=kari)
        assert wrong.status_code == 400
        done = client.post("/api/garmin/code", json={"code": "123456"}, headers=kari).json()
        assert (done["waiting_for_code"], done["connected"]) == (False, True)

        started = client.post("/api/garmin/backfill", json={"days": 3}, headers=kari).json()
        assert started["syncing"] is True
        assert started["backfill"]["days"] == 3
        runner = household.profiles["kari"].runner
        for _ in range(100):
            if not runner.running:
                break
            time.sleep(0.05)
        status = client.get("/api/garmin", headers=kari).json()
        assert status["backfill"] is None
        assert status["backfill_reached"] is not None
        other = client.get("/api/garmin", headers={"X-Profile": "kari-2"}).json()
        assert other["connected"] is False
