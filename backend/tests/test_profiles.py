import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.api.app import create_app
from garmin_coach.api.profile import ProfileRuntime, make_profile
from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.coach.notify import Notifier, ProfileNotifier
from garmin_coach.coach.usage import Spending, record_usage
from garmin_coach.config import Settings
from garmin_coach.evidence.library import index_entry, search
from garmin_coach.jobs import ScheduledProfile, SyncRunner, start_scheduler
from garmin_coach.models import ApiUsage, AthleteProfile, Evidence, EvidenceTopic
from garmin_coach.profiles import (
    ProfileError,
    adopt_single_database,
    create_profile,
    open_profile,
    open_research,
    profile_slugs,
)
from garmin_coach.sync import SyncService
from tests.garmin_data import FakeGarmin
from tests.test_evidence import fake_create


def settings_in(path: Path) -> Settings:
    return Settings.model_construct(data_dir=path, trimp_coefficient=1.92)


def evidence(pmid: str) -> Evidence:
    return Evidence(
        pmid=pmid,
        title="Heavy strength training for runners",
        authors="Hansen A",
        abstract="",
        publication_types="Review",
        claim="Heavy squats improve running economy",
        population="Runners",
        intervention="Squats",
        outcome="Economy",
        design="meta_analysis",
        effect="positive",
        takeaway="Lift heavy",
        limitations="None",
        grade="A",
        status="approved",
        created_at=datetime(2026, 11, 1),
    )


def test_profiles_are_separate_and_share_research(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    create_profile(settings, "jon", "Jon", 1.92)
    create_profile(settings, "kari", None, 1.67)
    with pytest.raises(ProfileError):
        create_profile(settings, "Kari Nordmann", None, 1.67)
    assert profile_slugs(settings) == ["jon", "kari"]

    research = open_research(settings)
    databases = {slug: open_profile(settings, slug) for slug in profile_slugs(settings)}
    spending = Spending([research, *databases.values()])
    with databases["kari"]() as session:
        record_usage(session, "claude-haiku-5-5", "chat", None, usage(1_000_000))
        session.commit()

    def runtime(slug: str, sessions: sessionmaker[Session]) -> ProfileRuntime:
        coach = Coach(
            sessions, None, coach_settings(settings), research=research, spending=spending
        )
        service = SyncService(FakeGarmin([]), sessions, request_delay=0, sleep=lambda _: None)
        return make_profile(slug, sessions, lambda: service, coach)

    app = create_app([runtime(s, d) for s, d in databases.items()], research, schedule_sync=False)
    client = TestClient(app)

    assert client.get("/api/profiles").json() == [
        {"slug": "jon", "name": "Jon"},
        {"slug": "kari", "name": "Kari"},
    ]
    assert client.get("/api/goals").status_code == 409
    kari = {"X-Profile": "kari"}
    goal = {"kind": "race", "title": "Birkebeinerløpet"}
    client.post("/api/goals", json=goal, headers=kari)
    assert [g["title"] for g in client.get("/api/goals", headers=kari).json()] == [goal["title"]]
    assert client.get("/api/goals", params={"profile": "jon"}).json() == []

    usage_out = client.get("/api/usage", headers=kari).json()
    assert usage_out["month_cost_usd"] == pytest.approx(0.1)
    assert client.get("/api/usage", headers={"X-Profile": "jon"}).json()[
        "household_cost_usd"
    ] == pytest.approx(0.1)

    with databases["kari"]() as session:
        record_usage(session, "claude-haiku-5-5", "chat", None, usage(1_000_000))
        session.commit()
    with research() as session:
        record_usage(session, "claude-haiku-5-5", "evidence", None, usage(1_000_000))
        session.commit()
    today = date.today().isoformat()
    assert client.get("/api/usage/daily", params={"days": 7}, headers=kari).json() == [
        {"day": today, "purpose": "chat", "cost_usd": pytest.approx(0.2), "calls": 2},
        {"day": today, "purpose": "evidence", "cost_usd": pytest.approx(0.1), "calls": 1},
    ]
    assert len(client.get("/api/usage", params={"recent": 1}, headers=kari).json()["recent"]) == 1

    topic = {"name": "Skiing", "query": "skiing", "weekly_limit": 2}
    client.post("/api/evidence/topics", json=topic, headers=kari)
    names = [t["name"] for t in client.get("/api/evidence/topics", headers=kari).json()]
    assert "Skiing" in names
    assert names == [t["name"] for t in client.get("/api/evidence/topics").json()]
    with databases["jon"]() as session:
        assert session.scalar(select(EvidenceTopic).where(EvidenceTopic.name == "Skiing")) is None


def usage(input_tokens: int) -> Any:
    response = fake_create()
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = 0
    return response.usage


def test_profile_notifier_links_to_the_profile() -> None:
    sent: list[str] = []

    class Recording(Notifier):
        def send(self, title: str, message: str, page: str = "#chat") -> bool:
            sent.append(f"{self.topic} {page}")
            return True

    topic: list[str | None] = [None]
    notifier = ProfileNotifier(Recording("https://ntfy.sh", None), "kari", lambda: topic[0])
    assert not notifier.enabled
    topic[0] = "kari-coach"
    assert notifier.enabled
    notifier.send("Hi", "Run today", "#plan")
    assert sent == ["kari-coach ?profile=kari#plan"]


def test_scheduler_has_jobs_per_profile(tmp_path: Path) -> None:
    def runner() -> SyncRunner:
        return SyncRunner(lambda: None)  # type: ignore[arg-type,return-value]

    scheduler = start_scheduler([ScheduledProfile("a", runner()), ScheduledProfile("b", runner())])
    try:
        jobs = {job.id: job for job in scheduler.get_jobs()}
        assert set(jobs) == {"recent_sync_a", "recent_sync_b"}
        fields = {field.name: str(field) for field in jobs["recent_sync_b"].trigger.fields}
        assert fields["minute"] == "15"
    finally:
        scheduler.shutdown(wait=False)


def test_adopt_moves_the_single_database(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    old = open_research(Settings.model_construct(data_dir=tmp_path / "old"))
    with old() as session:
        session.add(AthleteProfile(id=1, name="Jon"))
        for pmid in ("1", "2"):
            entry = evidence(pmid)
            session.add(entry)
            session.flush()
            index_entry(session, entry)
        record_usage(session, "claude-haiku-5-5", "evidence", None, usage(100_000))
        record_usage(session, "claude-haiku-5-5", "chat", None, usage(100_000))
        session.commit()
    old.kw["bind"].dispose()
    (tmp_path / "old" / "research.db").rename(settings.single_database_path)
    settings.single_tokens_dir.mkdir()
    (settings.single_tokens_dir / "garmin_tokens.json").write_text("{}")

    assert adopt_single_database(settings, "jon", "jon-coach", 1.92) == 2

    assert not settings.single_database_path.exists()
    assert (settings.profile_tokens_dir("jon") / "garmin_tokens.json").exists()
    with open_profile(settings, "jon")() as session:
        profile = session.get(AthleteProfile, 1)
        assert profile is not None
        assert (profile.name, profile.ntfy_topic, profile.trimp_coefficient) == (
            "Jon",
            "jon-coach",
            1.92,
        )
        assert list(session.scalars(select(ApiUsage.purpose))) == ["chat"]
    with open_research(settings)() as session:
        assert list(session.scalars(select(ApiUsage.purpose))) == ["evidence"]
        assert [e.pmid for e in search(session, "heavy squats")] == ["1", "2"]
    with pytest.raises(ProfileError):
        adopt_single_database(settings, "again", None, 1.92)
    connection = sqlite3.connect(settings.research_database_path)
    assert connection.execute("SELECT count(*) FROM evidence_topic").fetchone()[0] == 6
    connection.close()
