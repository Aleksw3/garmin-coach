import copy
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.api.app import create_app
from garmin_coach.api.coach_routes import chat_items
from garmin_coach.coach.agent import Coach, CoachSettings
from garmin_coach.coach.tools import ToolContext, run_tool, tool_definitions
from garmin_coach.coach.usage import cost_usd
from garmin_coach.models import ApiUsage, CoachNote, Conversation, Goal, Message
from garmin_coach.normalize import rebuild_all
from garmin_coach.sync import SyncService
from tests.garmin_data import FakeGarmin, activity_summary, daily

NOW = datetime(2026, 10, 28, 12, 0)
SETTINGS = CoachSettings("claude-sonnet-5-5", "low", 5.0, 1.92)


@dataclass
class Block:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None

    def model_dump(self, mode: str, exclude_none: bool) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if value is not None}


@dataclass
class Usage:
    input_tokens: int = 100
    cache_creation_input_tokens: int | None = 2000
    cache_read_input_tokens: int | None = 0
    output_tokens: int = 300


@dataclass
class Reply:
    content: list[Block]
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)


class FakeStream:
    def __init__(self, reply: Reply) -> None:
        self.reply = reply

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def __iter__(self) -> Iterator[SimpleNamespace]:
        for block in self.reply.content:
            if block.type == "text":
                yield SimpleNamespace(type="text", text=block.text)

    def get_final_message(self) -> Reply:
        return self.reply


class FakeClaude:
    def __init__(self, replies: list[Reply]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []

    def __call__(self, **params: Any) -> FakeStream:
        self.requests.append(copy.deepcopy(params))
        return FakeStream(self.replies.pop(0))


def tool_reply(name: str, tool_input: dict[str, Any], tool_id: str = "tool_1") -> Reply:
    return Reply(
        [
            Block("text", text="Checking."),
            Block("tool_use", id=tool_id, name=name, input=tool_input),
        ],
        stop_reason="tool_use",
    )


def text_reply(text: str) -> Reply:
    return Reply([Block("text", text=text)])


@pytest.fixture
def seeded(sessions: sessionmaker[Session]) -> sessionmaker[Session]:
    with sessions() as session:
        for offset in range(10):
            day = NOW.date() - timedelta(days=offset)
            for kind in ("stats", "sleep", "hrv"):
                raw_store.put_daily(session, day, kind, daily(kind, day))
        for activity_id, start in [(1, "2026-10-27 07:00:00"), (2, "2026-10-20 07:00:00")]:
            raw_store.put_activity(
                session, activity_id, "summary", activity_summary(activity_id, start)
            )
        rebuild_all(session)
        session.add(Goal(kind="race", title="Mountain Marathon", target_date=date(2027, 8, 28)))
        session.add(Conversation(id=1, created_at=NOW, updated_at=NOW))
        session.commit()
    return sessions


def make_coach(sessions: sessionmaker[Session], claude: FakeClaude, budget: float = 5.0) -> Coach:
    settings = CoachSettings(SETTINGS.model, SETTINGS.effort, budget, SETTINGS.trimp_coefficient)
    return Coach(sessions, claude, settings, now=lambda: NOW)


def test_reply_runs_tools_and_stores_the_turn(seeded: sessionmaker[Session]) -> None:
    claude = FakeClaude(
        [
            tool_reply("get_weekly_summary", {"start": "2026-10-19", "end": "2026-10-28"}),
            text_reply("You ran twice."),
        ]
    )
    events = list(make_coach(seeded, claude).reply(1, "How was my running?"))

    assert [e["type"] for e in events] == [
        "text",
        "tool_call",
        "tool_result",
        "text",
        "done",
    ]
    assert events[2]["ok"] is True
    first, second = claude.requests
    assert first["model"] == "claude-sonnet-5-5"
    assert first["output_config"] == {"effort": "low"}
    user_content = first["messages"][-1]["content"]
    assert user_content[0]["text"].startswith("<context>\nToday: Wednesday 2026-10-28")
    assert "Mountain Marathon" in user_content[0]["text"]
    assert user_content[1]["text"] == "How was my running?"
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "tool_1"
    assert "run" in tool_result["content"]
    assert second["messages"][:1] == first["messages"]

    with seeded() as session:
        messages = session.scalars(select(Message).order_by(Message.id)).all()
        assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
        usage = session.scalars(select(ApiUsage)).all()
        assert len(usage) == 2
        assert events[-1]["turn_cost_usd"] == pytest.approx(sum(u.cost_usd for u in usage))
        assert session.get(Conversation, 1).title == "How was my running?"  # type: ignore[union-attr]

        items = chat_items(list(messages))
    assert [i.role for i in items] == ["user", "coach"]
    assert items[1].text == "Checking.\n\nYou ran twice."
    assert items[1].tools[0].name == "get_weekly_summary"
    assert items[1].tools[0].ok is True


def test_next_turn_replays_history_unchanged(seeded: sessionmaker[Session]) -> None:
    claude = FakeClaude([text_reply("Hi."), text_reply("Again.")])
    coach = make_coach(seeded, claude)
    list(coach.reply(1, "Hello"))
    list(coach.reply(1, "Hello again"))

    first, second = claude.requests
    assert second["messages"][:1] == first["messages"]
    assert second["messages"][1] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "Hi."}],
    }
    assert second["system"] == first["system"]
    assert second["tools"] == first["tools"]


def test_invalid_tool_input_returns_an_error_result(seeded: sessionmaker[Session]) -> None:
    claude = FakeClaude(
        [tool_reply("get_load", {"start": "2026-10-28", "end": "2026-10-01"}), text_reply("Oops.")]
    )
    events = list(make_coach(seeded, claude).reply(1, "Load?"))

    assert next(e for e in events if e["type"] == "tool_result")["ok"] is False
    result = claude.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "start is after end" in result["content"]


def test_budget_blocks_chat(seeded: sessionmaker[Session]) -> None:
    with seeded() as session:
        session.add(
            ApiUsage(
                created_at=NOW,
                model="claude-sonnet-5-5",
                purpose="chat",
                input_tokens=0,
                cache_write_tokens=0,
                cache_read_tokens=0,
                output_tokens=0,
                cost_usd=5.01,
            )
        )
        session.commit()
    claude = FakeClaude([])
    events = list(make_coach(seeded, claude).reply(1, "Hi"))

    assert events[0]["type"] == "error"
    assert "budget" in events[0]["message"]
    assert claude.requests == []


def test_missing_api_key() -> None:
    coach = Coach(None, None, SETTINGS)  # type: ignore[arg-type]
    assert next(iter(coach.reply(1, "Hi")))["type"] == "error"


def test_tool_definitions_are_sorted_and_clean() -> None:
    definitions = tool_definitions()
    names = [d["name"] for d in definitions]

    assert names == sorted(names)
    assert "title" not in json.dumps([d["input_schema"] for d in definitions])
    assert all(d["input_schema"]["additionalProperties"] is False for d in definitions)


def test_tools_read_the_database(seeded: sessionmaker[Session]) -> None:
    with seeded() as session:
        context = ToolContext(session, NOW.date(), 1.92)

        activities, ok = run_tool(
            context, "list_activities", {"start": "2026-10-01", "end": "2026-10-28"}
        )
        assert ok
        assert activities.startswith("2 activities")
        assert "id 1 | 2026-10-27 07:00 | running (run)" in activities

        detail, ok = run_tool(context, "get_activity", {"activity_id": 1})
        assert detail.startswith("id 1 |")
        assert ok
        missing, ok = run_tool(context, "get_activity", {"activity_id": 99})
        assert not ok and "No activity" in missing

        wellness, ok = run_tool(
            context, "get_wellness", {"start": "2026-10-20", "end": "2026-10-28"}
        )
        assert ok
        assert "2026-10-28 | sleep" in wellness

        _, ok = run_tool(context, "save_note", {"text": "Left knee sore on descents"})
        assert ok
        notes, _ = run_tool(context, "get_notes", {"query": "knee"})
        assert "Left knee sore" in notes
        assert session.scalars(select(CoachNote)).one()

        unknown, ok = run_tool(context, "drop_tables", {})
        assert unknown == "Unknown tool drop_tables"
        assert not ok


def test_cost() -> None:
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 0, 0, 0) == pytest.approx(2.0)
    assert cost_usd("claude-sonnet-5-5", 0, 1_000_000, 1_000_000, 1_000_000) == pytest.approx(
        2.5 + 0.2 + 10.0
    )


def test_chat_api_streams_events(seeded: sessionmaker[Session]) -> None:
    claude = FakeClaude([text_reply("Hello from the coach.")])

    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), seeded, request_delay=0, sleep=lambda _: None)

    client = TestClient(
        create_app(seeded, make_service, make_coach(seeded, claude), schedule_sync=False)
    )
    created = client.post("/api/conversations").json()
    with client.stream(
        "POST", f"/api/conversations/{created['id']}/messages", json={"text": "Hi coach"}
    ) as response:
        lines = [line for line in response.iter_lines() if line.startswith("data: ")]
    events = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert events[0] == {"type": "text", "text": "Hello from the coach."}
    assert events[-1]["type"] == "done"

    detail = client.get(f"/api/conversations/{created['id']}").json()
    assert [item["text"] for item in detail["items"]] == ["Hi coach", "Hello from the coach."]
    assert client.get("/api/usage").json()["calls_this_month"] == 1

    goal = {"kind": "race", "title": "Test race", "target_date": "2027-06-01", "distance_km": 42}
    goal_id = client.post("/api/goals", json=goal).json()["id"]
    assert (
        client.put(f"/api/goals/{goal_id}", json={**goal, "status": "done"}).json()["status"]
        == "done"
    )
    assert client.put("/api/profile", json={"max_hr": 190}).json()["max_hr"] == 190
    assert client.delete(f"/api/conversations/{created['id']}").status_code == 204
