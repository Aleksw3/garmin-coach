import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from garmin_coach.api.routes import SessionDep
from garmin_coach.evidence.fetch import LAST_FETCH, EvidenceFetcher
from garmin_coach.evidence.library import citation, index_entry, search, set_status
from garmin_coach.evidence.summarize import DESIGNS, EFFECTS, GRADES
from garmin_coach.models import Evidence, EvidenceTopic
from garmin_coach.sync import get_state

router = APIRouter(prefix="/api/evidence")

Design = Literal[DESIGNS]  # type: ignore[valid-type]
Effect = Literal[EFFECTS]  # type: ignore[valid-type]


class EvidenceEdit(BaseModel):
    claim: str
    population: str
    intervention: str
    outcome: str
    design: Design
    sample_size: int | None = Field(default=None, ge=0)
    effect: Effect
    takeaway: str
    limitations: str
    notes: str | None = None


class EvidenceOut(EvidenceEdit):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int | None
    pmid: str
    doi: str | None
    title: str
    authors: str
    journal: str | None
    year: int | None
    abstract: str
    publication_types: str
    grade: str
    status: str
    disputed_by_id: int | None
    citation: str = ""
    created_at: datetime
    reviewed_at: datetime | None


class StatusIn(BaseModel):
    status: Literal["pending", "approved", "rejected"]


class DisputeIn(BaseModel):
    disputed_by_id: int | None


class TopicIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=3, max_length=2000)
    weekly_limit: int = Field(ge=0, le=20)
    active: bool = True


class TopicOut(TopicIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_fetched_at: datetime | None
    approved: int = 0
    pending: int = 0


class FetchStatusOut(BaseModel):
    running: bool
    available: bool
    last: dict[str, object] | None


def evidence_out(entry: Evidence) -> EvidenceOut:
    return EvidenceOut.model_validate(entry).model_copy(update={"citation": citation(entry)})


def find_entry(session: SessionDep, entry_id: int) -> Evidence:
    entry = session.get(Evidence, entry_id)
    if entry is None:
        raise HTTPException(404, "Evidence entry not found")
    return entry


def get_fetcher(request: Request) -> EvidenceFetcher | None:
    fetcher: EvidenceFetcher | None = request.app.state.evidence_fetcher
    return fetcher


@router.get("", response_model=list[EvidenceOut])
def list_evidence(
    session: SessionDep,
    status: Literal["pending", "approved", "rejected"] = "pending",
    q: Annotated[str | None, Query(max_length=300)] = None,
) -> list[EvidenceOut]:
    if q and status == "approved":
        entries = search(session, q, limit=50)
    else:
        entries = list(
            session.scalars(
                select(Evidence)
                .where(Evidence.status == status)
                .order_by(Evidence.grade, Evidence.year.desc(), Evidence.id)
            )
        )
    return [evidence_out(entry) for entry in entries]


@router.put("/{entry_id}", response_model=EvidenceOut)
def edit_evidence(session: SessionDep, entry_id: int, body: EvidenceEdit) -> EvidenceOut:
    entry = find_entry(session, entry_id)
    for name, value in body.model_dump().items():
        setattr(entry, name, value)
    entry.grade = GRADES[entry.design]
    session.flush()
    index_entry(session, entry)
    session.commit()
    return evidence_out(entry)


@router.post("/{entry_id}/status", response_model=EvidenceOut)
def change_status(session: SessionDep, entry_id: int, body: StatusIn) -> EvidenceOut:
    entry = find_entry(session, entry_id)
    set_status(session, entry, body.status, datetime.now())
    session.commit()
    return evidence_out(entry)


@router.put("/{entry_id}/disputed", response_model=EvidenceOut)
def set_disputed(session: SessionDep, entry_id: int, body: DisputeIn) -> EvidenceOut:
    entry = find_entry(session, entry_id)
    if body.disputed_by_id is not None:
        if body.disputed_by_id == entry_id:
            raise HTTPException(422, "An entry cannot dispute itself")
        find_entry(session, body.disputed_by_id)
    entry.disputed_by_id = body.disputed_by_id
    session.commit()
    return evidence_out(entry)


def topic_out(session: SessionDep, topic: EvidenceTopic) -> TopicOut:
    counts = {
        status: count
        for status, count in session.execute(
            select(Evidence.status, func.count())
            .where(Evidence.topic_id == topic.id)
            .group_by(Evidence.status)
        )
    }
    return TopicOut.model_validate(topic).model_copy(
        update={"approved": counts.get("approved", 0), "pending": counts.get("pending", 0)}
    )


@router.get("/topics", response_model=list[TopicOut])
def list_topics(session: SessionDep) -> list[TopicOut]:
    topics = session.scalars(select(EvidenceTopic).order_by(EvidenceTopic.id))
    return [topic_out(session, topic) for topic in topics]


@router.post("/topics", response_model=TopicOut)
def create_topic(session: SessionDep, body: TopicIn) -> TopicOut:
    topic = EvidenceTopic(**body.model_dump())
    session.add(topic)
    session.commit()
    return topic_out(session, topic)


def find_topic(session: SessionDep, topic_id: int) -> EvidenceTopic:
    topic = session.get(EvidenceTopic, topic_id)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    return topic


@router.put("/topics/{topic_id}", response_model=TopicOut)
def update_topic(session: SessionDep, topic_id: int, body: TopicIn) -> TopicOut:
    topic = find_topic(session, topic_id)
    for name, value in body.model_dump().items():
        setattr(topic, name, value)
    session.commit()
    return topic_out(session, topic)


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(session: SessionDep, topic_id: int) -> Response:
    session.delete(find_topic(session, topic_id))
    session.commit()
    return Response(status_code=204)


def fetch_status(session: SessionDep, fetcher: EvidenceFetcher | None) -> FetchStatusOut:
    last = get_state(session, LAST_FETCH)
    return FetchStatusOut(
        running=fetcher.running if fetcher else False,
        available=fetcher is not None,
        last=json.loads(last) if last else None,
    )


@router.get("/fetch", response_model=FetchStatusOut)
def get_fetch(session: SessionDep, request: Request) -> FetchStatusOut:
    return fetch_status(session, get_fetcher(request))


@router.post("/fetch", response_model=FetchStatusOut)
def start_fetch(session: SessionDep, request: Request) -> FetchStatusOut:
    fetcher = get_fetcher(request)
    if fetcher is None:
        raise HTTPException(409, "Fetching needs ANTHROPIC_API_KEY in .env for the summaries")
    fetcher.start_in_background()
    return fetch_status(session, fetcher)
