import json
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from garmin_coach.api.routes import SessionDep
from garmin_coach.coach.agent import Coach
from garmin_coach.coach.usage import month_spend, month_start
from garmin_coach.models import ApiUsage, AthleteProfile, CoachNote, Conversation, Goal, Message

router = APIRouter(prefix="/api")

RECENT_USAGE_ROWS = 20


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    updated_at: datetime


class ToolCallOut(BaseModel):
    id: str
    name: str
    input: dict[str, Any]
    ok: bool | None


class ChatItemOut(BaseModel):
    role: Literal["user", "coach"]
    text: str
    tools: list[ToolCallOut]
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    items: list[ChatItemOut]


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    purpose: Literal["chat", "plan"] = "chat"


class ProfileIn(BaseModel):
    name: str | None = None
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    sex: str | None = None
    height_cm: float | None = Field(default=None, gt=0)
    max_hr: int | None = Field(default=None, gt=0, lt=250)
    training_days: str | None = None
    injuries: str | None = None
    equipment: str | None = None
    notes: str | None = None


class ProfileOut(ProfileIn):
    model_config = ConfigDict(from_attributes=True)


class GoalIn(BaseModel):
    kind: Literal["race", "strength", "habit", "other"]
    title: str = Field(min_length=1, max_length=200)
    target_date: date | None = None
    target: str | None = None
    distance_km: float | None = None
    elevation_gain_m: float | None = None
    terrain: str | None = None
    cutoffs: str | None = None
    notes: str | None = None
    priority: Literal["A", "B", "C"] = "A"
    status: Literal["active", "done", "dropped"] = "active"


class GoalOut(GoalIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    text: str


class UsageRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    model: str
    purpose: str
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    cost_usd: float


class UsageOut(BaseModel):
    month_cost_usd: float
    budget_usd: float
    calls_this_month: int
    chat_model: str
    plan_model: str
    background_model: str
    recent: list[UsageRowOut]


def get_coach(request: Request) -> Coach:
    coach: Coach = request.app.state.coach
    return coach


def chat_items(messages: list[Message]) -> list[ChatItemOut]:
    contents = [(message, json.loads(message.content)) for message in messages]
    tool_ok = {
        block["tool_use_id"]: not block.get("is_error", False)
        for message, content in contents
        if message.role == "user"
        for block in content
        if block.get("type") == "tool_result"
    }
    items: list[ChatItemOut] = []
    for message, content in contents:
        if message.role == "user":
            if message.display_text is not None:
                items.append(
                    ChatItemOut(
                        role="user",
                        text=message.display_text,
                        tools=[],
                        created_at=message.created_at,
                    )
                )
            continue
        if not items or items[-1].role != "coach":
            items.append(
                ChatItemOut(role="coach", text="", tools=[], created_at=message.created_at)
            )
        item = items[-1]
        for block in content:
            if block.get("type") == "text":
                item.text = f"{item.text}\n\n{block['text']}" if item.text else block["text"]
            elif block.get("type") == "tool_use":
                item.tools.append(
                    ToolCallOut(
                        id=block["id"],
                        name=block["name"],
                        input=block.get("input") or {},
                        ok=tool_ok.get(block["id"]),
                    )
                )
    return items


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(session: SessionDep) -> list[Conversation]:
    return list(session.scalars(select(Conversation).order_by(Conversation.updated_at.desc())))


@router.post("/conversations", response_model=ConversationOut)
def create_conversation(session: SessionDep) -> Conversation:
    now = datetime.now()
    conversation = Conversation(created_at=now, updated_at=now)
    session.add(conversation)
    session.commit()
    return conversation


def find_conversation(session: SessionDep, conversation_id: int) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(session: SessionDep, conversation_id: int) -> ConversationDetailOut:
    conversation = find_conversation(session, conversation_id)
    messages = session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    ).all()
    return ConversationDetailOut(
        id=conversation.id,
        title=conversation.title,
        updated_at=conversation.updated_at,
        items=chat_items(list(messages)),
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(session: SessionDep, conversation_id: int) -> Response:
    session.delete(find_conversation(session, conversation_id))
    session.commit()
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    session: SessionDep, request: Request, conversation_id: int, body: NewMessage
) -> StreamingResponse:
    find_conversation(session, conversation_id)
    coach = get_coach(request)

    def events() -> Iterator[str]:
        for event in coach.reply(conversation_id, body.text, body.purpose):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@router.get("/profile", response_model=ProfileOut)
def get_profile(session: SessionDep) -> AthleteProfile | ProfileOut:
    return session.get(AthleteProfile, 1) or ProfileOut()


@router.put("/profile", response_model=ProfileOut)
def put_profile(session: SessionDep, body: ProfileIn) -> AthleteProfile:
    profile = session.get(AthleteProfile, 1) or AthleteProfile(id=1)
    for field, value in body.model_dump().items():
        setattr(profile, field, value)
    session.add(profile)
    session.commit()
    return profile


@router.get("/goals", response_model=list[GoalOut])
def list_goals(session: SessionDep) -> list[Goal]:
    return list(
        session.scalars(select(Goal).order_by(Goal.status, Goal.priority, Goal.target_date))
    )


@router.post("/goals", response_model=GoalOut)
def create_goal(session: SessionDep, body: GoalIn) -> Goal:
    goal = Goal(**body.model_dump())
    session.add(goal)
    session.commit()
    return goal


def find_goal(session: SessionDep, goal_id: int) -> Goal:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    return goal


@router.put("/goals/{goal_id}", response_model=GoalOut)
def update_goal(session: SessionDep, goal_id: int, body: GoalIn) -> Goal:
    goal = find_goal(session, goal_id)
    for field, value in body.model_dump().items():
        setattr(goal, field, value)
    session.commit()
    return goal


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(session: SessionDep, goal_id: int) -> Response:
    session.delete(find_goal(session, goal_id))
    session.commit()
    return Response(status_code=204)


@router.get("/notes", response_model=list[NoteOut])
def list_notes(session: SessionDep) -> list[CoachNote]:
    return list(session.scalars(select(CoachNote).order_by(CoachNote.created_at.desc())))


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(session: SessionDep, note_id: int) -> Response:
    note = session.get(CoachNote, note_id)
    if note is None:
        raise HTTPException(404, "Note not found")
    session.delete(note)
    session.commit()
    return Response(status_code=204)


@router.get("/usage", response_model=UsageOut)
def get_usage(session: SessionDep, request: Request) -> UsageOut:
    settings = get_coach(request).settings
    today = date.today()
    calls = session.scalar(
        select(func.count(ApiUsage.id)).where(ApiUsage.created_at >= month_start(today))
    )
    recent = session.scalars(
        select(ApiUsage).order_by(ApiUsage.id.desc()).limit(RECENT_USAGE_ROWS)
    ).all()
    return UsageOut(
        month_cost_usd=month_spend(session, today),
        budget_usd=settings.monthly_budget_usd,
        calls_this_month=calls or 0,
        chat_model=settings.choice("chat").model,
        plan_model=settings.choice("plan").model,
        background_model=settings.choice("checkin").model,
        recent=[UsageRowOut.model_validate(row) for row in recent],
    )
