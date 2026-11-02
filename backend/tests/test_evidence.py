import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.api.app import create_app
from garmin_coach.coach.agent import Coach, coach_settings
from garmin_coach.coach.tools import ToolContext, run_tool
from garmin_coach.config import Settings
from garmin_coach.evidence.fetch import EvidenceFetcher
from garmin_coach.evidence.library import SEED_PMIDS, search, seed_topics
from garmin_coach.evidence.pubmed import Paper, PubMed, parse_articles
from garmin_coach.evidence.summarize import Summarizer, design_for
from garmin_coach.models import ApiUsage, Evidence, EvidenceTopic
from garmin_coach.sync import SyncService
from tests.garmin_data import FakeGarmin

NOW = datetime(2026, 11, 2, 7, 0)

ARTICLE_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>29249083</PMID><Article>
<Journal><JournalIssue><PubDate><Year>2018</Year></PubDate></JournalIssue>
<ISOAbbreviation>Sports Med</ISOAbbreviation></Journal>
<ArticleTitle>Effects of Strength Training on <i>Running</i> Performance</ArticleTitle>
<Abstract><AbstractText Label="METHODS">24 studies.</AbstractText>
<AbstractText Label="RESULTS">Economy improved.</AbstractText></Abstract>
<AuthorList><Author><LastName>Blagrove</LastName><Initials>RC</Initials></Author>
<Author><LastName>Howatson</LastName><Initials>G</Initials></Author></AuthorList>
<PublicationTypeList><PublicationType>Journal Article</PublicationType>
<PublicationType>Systematic Review</PublicationType></PublicationTypeList>
</Article></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="pubmed">29249083</ArticleId>
<ArticleId IdType="doi">10.1007/s40279-017-0835-7</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


def paper(pmid: str, title: str = "Strength training for trail runners") -> Paper:
    return Paper(
        pmid=pmid,
        doi=f"10.1000/{pmid}",
        title=title,
        authors=["Hansen A", "Berg B"],
        journal="Sports Med",
        year=2025,
        abstract="Heavy strength training improved running economy by 4%.",
        publication_types=["Journal Article", "Randomized Controlled Trial"],
    )


class FakePubMed(PubMed):
    def __init__(self, results: dict[str, list[str]]) -> None:
        self.results = results
        self.searches: list[tuple[str, int]] = []

    def search(self, term: str, limit: int) -> list[str]:
        self.searches.append((term, limit))
        return next((ids for key, ids in self.results.items() if term.startswith(key)), [])[:limit]

    def fetch(self, pmids: list[str]) -> list[Paper]:
        return [paper(pmid) for pmid in pmids]


def fake_create(**params: Any) -> SimpleNamespace:
    summary = {
        "claim": "Heavy strength training improves running economy.",
        "population": "Trained trail runners",
        "intervention": "Twice weekly heavy squats for 10 weeks",
        "outcome": "Running economy",
        "design": "other",
        "sample_size": 24,
        "effect": "positive",
        "takeaway": "Keep two heavy lower-body sessions a week.",
        "limitations": "Small sample",
    }
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(summary))],
        usage=SimpleNamespace(
            input_tokens=900,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            output_tokens=200,
        ),
    )


@pytest.fixture
def topics(sessions: sessionmaker[Session]) -> sessionmaker[Session]:
    with sessions() as session:
        session.add(EvidenceTopic(id=1, name="Running", query="running", weekly_limit=2))
        session.add(EvidenceTopic(id=2, name="Off", query="skiing", weekly_limit=2, active=False))
        session.commit()
    return sessions


def make_fetcher(
    sessions: sessionmaker[Session], pubmed: PubMed, budget: float = 5.0
) -> EvidenceFetcher:
    summarizer = Summarizer(fake_create, "claude-haiku-5-5")
    return EvidenceFetcher(sessions, pubmed, summarizer, budget, now=lambda: NOW)


def test_parse_pubmed_xml() -> None:
    (article,) = parse_articles(ARTICLE_XML)

    assert article.pmid == "29249083"
    assert article.doi == "10.1007/s40279-017-0835-7"
    assert article.title == "Effects of Strength Training on Running Performance"
    assert article.authors == ["Blagrove RC", "Howatson G"]
    assert article.year == 2018
    assert article.abstract == "METHODS: 24 studies.\nRESULTS: Economy improved."
    assert "Systematic Review" in article.publication_types


def test_seed_topics_once(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        seed_topics(session)
        seed_topics(session)
        session.commit()
        limits = {t.name: t.weekly_limit for t in session.scalars(select(EvidenceTopic))}
    assert limits["Running"] == 5
    assert limits["General training research"] == 2
    assert len(limits) == 6


def test_fetch_adds_new_papers_up_to_the_weekly_limit(topics: sessionmaker[Session]) -> None:
    pubmed = FakePubMed({"running": ["1", "2", "3"]})
    result = make_fetcher(topics, pubmed).fetch_all()

    assert result is not None
    assert result.added == len(SEED_PMIDS) + 2
    assert pubmed.searches == [(pubmed.searches[0][0], 8)]
    assert "hasabstract" in pubmed.searches[0][0]
    with topics() as session:
        entries = session.scalars(select(Evidence).where(Evidence.topic_id == 1)).all()
        assert [e.pmid for e in entries] == ["1", "2"]
        assert entries[0].design == "randomized_trial"
        assert entries[0].grade == "B"
        assert entries[0].status == "pending"
        assert entries[0].authors == "Hansen A; Berg B"
        assert session.scalars(select(ApiUsage.purpose)).first() == "evidence"

    second = make_fetcher(topics, pubmed).fetch_all()
    assert second is not None and second.added == 1
    with topics() as session:
        assert session.scalar(select(Evidence.pmid).where(Evidence.pmid == "3")) == "3"


def test_fetch_stops_at_the_budget(topics: sessionmaker[Session]) -> None:
    result = make_fetcher(topics, FakePubMed({"running": ["1"]}), budget=0.0).fetch_all()

    assert result is not None and result.added == 0
    assert any("budget" in error for error in result.errors)


def test_review_search_and_dispute(topics: sessionmaker[Session]) -> None:
    make_fetcher(topics, FakePubMed({"running": ["1", "2"]})).fetch_all()

    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), topics, request_delay=0, sleep=lambda _: None)

    coach = Coach(topics, None, coach_settings(Settings.model_construct()))
    client = TestClient(create_app(topics, make_service, coach, schedule_sync=False))

    queue = client.get("/api/evidence").json()
    assert len(queue) == len(SEED_PMIDS) + 2
    first, second = (e for e in queue if e["pmid"] in ("1", "2"))
    assert first["citation"] == "Hansen A et al. (2025), Sports Med"
    with topics() as session:
        assert search(session, "strength running") == []

    edited = {**{k: first[k] for k in ("claim", "population", "intervention", "outcome")}}
    edited |= {"design": "meta_analysis", "sample_size": 300, "effect": "positive"}
    edited |= {"takeaway": "Lift heavy twice a week.", "limitations": "Mixed", "notes": "Checked"}
    assert client.put(f"/api/evidence/{first['id']}", json=edited).json()["grade"] == "A"
    client.post(f"/api/evidence/{first['id']}/status", json={"status": "approved"})
    client.post(f"/api/evidence/{second['id']}/status", json={"status": "approved"})
    client.put(f"/api/evidence/{first['id']}/disputed", json={"disputed_by_id": second["id"]})

    approved = client.get(
        "/api/evidence", params={"status": "approved", "q": "heavy squats"}
    ).json()
    assert {e["id"] for e in approved} == {first["id"], second["id"]}
    with topics() as session:
        context = ToolContext(session, NOW, 1.92)
        output, ok = run_tool(context, "search_evidence", {"query": "strength training economy"})
    assert ok
    assert f"evidence {first['id']} | Hansen A et al. (2025), Sports Med | doi 10.1000/1" in output
    assert "grade A (meta_analysis, n=300)" in output
    assert f"disputed by evidence {second['id']}" in output
    assert "reviewer note: Checked" in output

    client.post(f"/api/evidence/{second['id']}/status", json={"status": "rejected"})
    with topics() as session:
        assert [e.id for e in search(session, "heavy squats")] == [first["id"]]

    topics_out = client.get("/api/evidence/topics").json()
    assert topics_out[0]["approved"] == 1
    status = client.get("/api/evidence/fetch").json()
    assert (status["running"], status["available"]) == (False, False)
    assert status["last"]["added"] == len(SEED_PMIDS) + 2
    assert client.post("/api/evidence/fetch").status_code == 409


def test_design_prefers_pubmed_publication_types() -> None:
    review = paper("5")
    review.publication_types = ["Journal Article", "Review"]
    assert design_for(review, "systematic_review") == "narrative_review"
    assert design_for(review, "observational") == "observational"
    review.publication_types = ["Journal Article", "Systematic Review"]
    assert design_for(review, "narrative_review") == "systematic_review"
