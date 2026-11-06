import json
import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.usage import Spending, record_usage
from garmin_coach.evidence.library import SEED_PMIDS, index_entry
from garmin_coach.evidence.pubmed import STUDY_FILTER, Paper, PubMed
from garmin_coach.evidence.summarize import Summarizer
from garmin_coach.models import Evidence, EvidenceTopic
from garmin_coach.sync import set_state

log = logging.getLogger(__name__)

LAST_FETCH = "evidence_last_fetch"
SEARCH_OVERSHOOT = 4


def paper_of(entry: Evidence) -> Paper:
    return Paper(
        pmid=entry.pmid,
        doi=entry.doi,
        title=entry.title,
        authors=entry.authors.split("; "),
        journal=entry.journal,
        year=entry.year,
        abstract=entry.abstract,
        publication_types=entry.publication_types.split(", "),
    )


@dataclass
class FetchResult:
    started_at: str
    finished_at: str | None = None
    added: int = 0
    errors: list[str] = field(default_factory=list)


class EvidenceFetcher:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        pubmed: PubMed,
        summarizer: Summarizer,
        monthly_budget_usd: float,
        now: Callable[[], datetime] = datetime.now,
        spending: Callable[[date], float] | None = None,
    ) -> None:
        self.sessions = sessions
        self.spending = spending or Spending([sessions])
        self.pubmed = pubmed
        self.summarizer = summarizer
        self.monthly_budget_usd = monthly_budget_usd
        self.now = now
        self.task: str | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    @property
    def ready(self) -> bool:
        return self.summarizer.create is not None

    def start_in_background(self) -> bool:
        if self.running:
            return False
        threading.Thread(target=self.fetch_all, daemon=True).start()
        return True

    def start_rewrite_in_background(self) -> bool:
        if self.running:
            return False
        threading.Thread(target=self.rewrite_takeaways, daemon=True).start()
        return True

    def _known(self, session: Session, pmids: list[str]) -> set[str]:
        return set(session.scalars(select(Evidence.pmid).where(Evidence.pmid.in_(pmids))))

    def _store(self, papers: list[Paper], topic_id: int | None, result: FetchResult) -> None:
        for paper in papers:
            if self.spending(self.now().date()) >= self.monthly_budget_usd:
                result.errors.append("Stopped: the monthly API budget is used up")
                return
            try:
                summary, usage = self.summarizer.summarize(paper)
            except Exception as error:
                log.exception("Summarizing PubMed %s failed", paper.pmid)
                result.errors.append(f"PubMed {paper.pmid}: {error}")
                continue
            with self.sessions() as session:
                record_usage(session, self.summarizer.model, "evidence", None, usage)
                session.add(
                    Evidence(
                        topic_id=topic_id,
                        pmid=paper.pmid,
                        doi=paper.doi,
                        title=paper.title,
                        authors="; ".join(paper.authors),
                        journal=paper.journal,
                        year=paper.year,
                        abstract=paper.abstract,
                        publication_types=", ".join(paper.publication_types),
                        design=summary.design,
                        grade=summary.grade,
                        claim=summary.claim,
                        population=summary.population,
                        intervention=summary.intervention,
                        outcome=summary.outcome,
                        sample_size=summary.sample_size,
                        effect=summary.effect,
                        takeaway=summary.takeaway,
                        limitations=summary.limitations,
                        status="pending",
                        created_at=self.now(),
                    )
                )
                session.commit()
            result.added += 1

    def rewrite_takeaways(self) -> int | None:
        if not self.ready or not self._lock.acquire(blocking=False):
            return None
        self.task = "rewrite"
        rewritten = 0
        try:
            with self.sessions() as session:
                for entry in session.scalars(select(Evidence).order_by(Evidence.id)).all():
                    if self.spending(self.now().date()) >= self.monthly_budget_usd:
                        log.warning("Stopped: the monthly API budget is used up")
                        break
                    try:
                        summary, usage = self.summarizer.summarize(paper_of(entry))
                    except Exception:
                        log.exception("Rewriting the takeaway of evidence %d failed", entry.id)
                        continue
                    record_usage(session, self.summarizer.model, "evidence", None, usage)
                    entry.takeaway = summary.takeaway
                    index_entry(session, entry)
                    session.commit()
                    rewritten += 1
                    log.info("Evidence %d, %s: %s", entry.id, entry.title, entry.takeaway)
        finally:
            self.task = None
            self._lock.release()
        return rewritten

    def _fetch_seeds(self, result: FetchResult) -> None:
        with self.sessions() as session:
            missing = [p for p in SEED_PMIDS if p not in self._known(session, list(SEED_PMIDS))]
        self._store(self.pubmed.fetch(missing), None, result)

    def _fetch_topic(self, topic_id: int, result: FetchResult) -> None:
        with self.sessions() as session:
            topic = session.get_one(EvidenceTopic, topic_id)
            name, query, limit = topic.name, topic.query, topic.weekly_limit
        pmids = self.pubmed.search(query + STUDY_FILTER, limit * SEARCH_OVERSHOOT)
        with self.sessions() as session:
            known = self._known(session, pmids)
        new = [pmid for pmid in pmids if pmid not in known][:limit]
        log.info("Evidence topic %s: %d new papers", name, len(new))
        self._store(self.pubmed.fetch(new), topic_id, result)
        with self.sessions() as session:
            session.get_one(EvidenceTopic, topic_id).last_fetched_at = self.now()
            session.commit()

    def fetch_all(self) -> FetchResult | None:
        if not self.ready or not self._lock.acquire(blocking=False):
            return None
        self.task = "fetch"
        result = FetchResult(started_at=self.now().isoformat(timespec="seconds"))
        try:
            try:
                self._fetch_seeds(result)
            except Exception as error:
                log.exception("Fetching the seed papers failed")
                result.errors.append(f"Seed papers: {error}")
            with self.sessions() as session:
                topic_ids = list(
                    session.scalars(select(EvidenceTopic.id).where(EvidenceTopic.active))
                )
            for topic_id in topic_ids:
                try:
                    self._fetch_topic(topic_id, result)
                except Exception as error:
                    log.exception("Fetching evidence topic %d failed", topic_id)
                    result.errors.append(f"Topic {topic_id}: {error}")
        finally:
            result.finished_at = self.now().isoformat(timespec="seconds")
            with self.sessions() as session:
                set_state(session, LAST_FETCH, json.dumps(asdict(result)))
                session.commit()
            self.task = None
            self._lock.release()
        return result
