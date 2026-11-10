import copy
import json
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.api.coach_routes import chat_items
from garmin_coach.coach.agent import SUMMARY_PROMPT, Coach, CoachError, coach_settings, title_from
from garmin_coach.coach.notify import Notifier
from garmin_coach.coach.proactive import ProactiveCoach
from garmin_coach.coach.prompt import context_block
from garmin_coach.coach.tools import ToolContext, run_tool, tool_definitions
from garmin_coach.coach.usage import cost_usd
from garmin_coach.config import Settings
from garmin_coach.models import (
    Activity,
    ActivityFeedback,
    ApiUsage,
    CoachNote,
    Conversation,
    Goal,
    Message,
)
from garmin_coach.normalize import rebuild_all
from garmin_coach.sync import SyncService
from tests.apps import single_app
from tests.garmin_data import FakeGarmin, activity_summary, daily

NOW = datetime(2026, 10, 28, 12, 0)
SETTINGS = coach_settings(Settings.model_construct())


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
    settings = replace(SETTINGS, monthly_budget_usd=budget)
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


def test_compacting_starts_the_history_at_a_summary(seeded: sessionmaker[Session]) -> None:
    claude = FakeClaude(
        [text_reply("Hi."), text_reply("- Left knee is sore"), text_reply("Rest the knee.")]
    )
    coach = make_coach(seeded, claude)
    list(coach.reply(1, "My left knee hurts"))
    assert coach.compact(1) == "- Left knee is sore"
    list(coach.reply(1, "What now?"))

    _, summary_request, next_request = claude.requests
    assert summary_request["tool_choice"] == {"type": "none"}
    assert summary_request["model"] == "claude-haiku-5-5"
    assert summary_request["messages"][-1]["content"][-1]["text"] == SUMMARY_PROMPT
    assert "tool_choice" not in next_request
    [turn] = next_request["messages"]
    assert turn["role"] == "user"
    assert turn["content"][0]["text"].endswith("- Left knee is sore")
    assert turn["content"][-1]["text"] == "What now?"

    with seeded() as session:
        items = chat_items(
            list(session.scalars(select(Message).where(Message.conversation_id == 1)))
        )
    assert [i.role for i in items] == ["user", "coach", "summary", "user", "coach"]
    with pytest.raises(CoachError, match="no messages"):
        coach.compact(2)


def test_compacting_twice_needs_new_messages(seeded: sessionmaker[Session]) -> None:
    coach = make_coach(seeded, FakeClaude([text_reply("Hi."), text_reply("- Summary")]))
    list(coach.reply(1, "Hello"))
    coach.compact(1)
    with pytest.raises(CoachError, match="Nothing new"):
        coach.compact(1)


def test_titles_keep_the_whole_first_line() -> None:
    question = "How should I split my hill sessions and long runs over the next eight weeks?"
    assert title_from(f"{question}\nMore detail") == question
    assert title_from("x" * 300) == "x" * 197 + "..."


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
    assert '"title": "' not in json.dumps([d["input_schema"] for d in definitions])
    assert all(d["input_schema"]["additionalProperties"] is False for d in definitions)


def test_tools_read_the_database(seeded: sessionmaker[Session]) -> None:
    with seeded() as session:
        context = ToolContext(session, NOW, 1.92)

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
        single_app(seeded, make_service, make_coach(seeded, claude), schedule_sync=False)
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
    assert detail["cost_usd"] == pytest.approx(events[-1]["turn_cost_usd"])
    assert detail["context_tokens"] == 2100
    assert client.get("/api/usage").json()["calls_this_month"] == 1

    claude.replies.append(text_reply("- Said hi"))
    compacted = client.post(f"/api/conversations/{created['id']}/compact").json()
    summary = compacted["items"][-1]
    assert (summary["role"], summary["text"]) == ("summary", "- Said hi")
    assert compacted["context_tokens"] == 0
    assert client.post(f"/api/conversations/{created['id']}/compact").status_code == 409

    goal = {"kind": "race", "title": "Test race", "target_date": "2027-06-01", "distance_km": 42}
    goal_id = client.post("/api/goals", json=goal).json()["id"]
    assert (
        client.put(f"/api/goals/{goal_id}", json={**goal, "status": "done"}).json()["status"]
        == "done"
    )
    assert client.put("/api/profile", json={"max_hr": 190}).json()["max_hr"] == 190
    assert client.delete(f"/api/conversations/{created['id']}").status_code == 204


def session_spec(day: str, title: str = "Easy run", **extra: Any) -> dict[str, Any]:
    return {"day": day, "sport": "run", "kind": "easy", "title": title, "duration_min": 45, **extra}


def test_plan_proposals_change_the_plan_only_when_accepted(seeded: sessionmaker[Session]) -> None:
    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), seeded, request_delay=0, sleep=lambda _: None)

    client = TestClient(single_app(seeded, make_service, make_coach(seeded, FakeClaude([]))))
    with seeded() as session:
        context = ToolContext(session, NOW, 1.92, conversation_id=1)
        output, ok = run_tool(
            context,
            "propose_plan",
            {
                "summary": "Base block",
                "reason": "Volume dropped",
                "plan": {
                    "title": "Base",
                    "goal_id": 1,
                    "sessions": [
                        session_spec("2026-11-02"),
                        session_spec("2026-11-04", "Hills", kind="hills", elevation_gain_m=500),
                        {"day": "2026-11-05", "sport": "rest", "kind": "rest", "title": "Rest"},
                    ],
                },
            },
        )
        session.commit()
    assert ok, output
    calendar = {"start": "2026-11-01", "end": "2026-11-08"}
    assert client.get("/api/plan", params=calendar).json()["sessions"] == []

    proposals = client.get("/api/proposals").json()
    assert [p["summary"] for p in proposals] == ["Base block"]
    assert client.post(f"/api/proposals/{proposals[0]['id']}/accept").json()["status"] == "accepted"
    sessions = client.get("/api/plan", params=calendar).json()["sessions"]
    assert [s["title"] for s in sessions] == ["Easy run", "Hills", "Rest"]
    assert client.post(f"/api/proposals/{proposals[0]['id']}/accept").status_code == 409

    hills, rest = sessions[1]["id"], sessions[2]["id"]
    with seeded() as session:
        context = ToolContext(session, NOW, 1.92, conversation_id=1)
        plan_text, _ = run_tool(context, "get_plan", {"start": "2026-11-01", "end": "2026-11-08"})
        assert (
            f"session {hills} | 2026-11-04 Wed | run hills | Hills | 45 min, 500 m up" in plan_text
        )
        output, ok = run_tool(
            context,
            "propose_changes",
            {
                "summary": "Move hills",
                "reason": "Low HRV",
                "changes": [
                    {
                        "op": "update",
                        "session_id": hills,
                        "session": session_spec("2026-11-06", "Hills"),
                    },
                    {"op": "remove", "session_id": rest},
                    {"op": "add", "session": session_spec("2026-11-04", "Recovery jog")},
                ],
            },
        )
        assert ok, output
        missing, ok = run_tool(
            context,
            "propose_changes",
            {"summary": "x", "reason": "x", "changes": [{"op": "remove", "session_id": 999}]},
        )
        assert not ok and "999" in missing
        session.commit()

    proposal = client.get("/api/proposals").json()[0]
    assert proposal["changes"][0]["current"]["day"] == "2026-11-04"
    client.post(f"/api/proposals/{proposal['id']}/accept")
    sessions = client.get("/api/plan", params=calendar).json()["sessions"]
    assert [(s["day"], s["title"]) for s in sessions] == [
        ("2026-11-02", "Easy run"),
        ("2026-11-04", "Recovery jog"),
        ("2026-11-06", "Hills"),
    ]
    assert client.patch(f"/api/sessions/{hills}", json={"skipped": True}).json()["skipped"]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    requests: list[Any] = []

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def urlopen(request: Any, timeout: float) -> Response:
        requests.append(request)
        return Response()

    monkeypatch.setattr("garmin_coach.coach.notify.urllib.request.urlopen", urlopen)
    return requests


def test_notifier_posts_to_the_topic(sent: list[Any]) -> None:
    assert not Notifier("https://ntfy.sh", None).send("Title", "Body")
    notifier = Notifier("https://ntfy.sh/", "my topic", "token", "http://coach.lan:8000/")
    assert notifier.send("Morning check-in", "Rest today")

    request = sent[0]
    assert request.full_url.startswith("https://ntfy.sh/my%20topic?title=Morning+check-in")
    assert "click=http%3A%2F%2Fcoach.lan%3A8000%2F%23chat" in request.full_url
    assert request.data == b"Rest today"
    assert request.get_header("Authorization") == "Bearer token"


def test_proactive_messages_go_to_the_weekly_coach_thread(
    seeded: sessionmaker[Session], sent: list[Any]
) -> None:
    claude = FakeClaude(
        [
            tool_reply("get_wellness", {"start": "2026-10-21", "end": "2026-10-28"}),
            text_reply("You look recovered. Run the hills as planned."),
            text_reply("Good steady run."),
        ]
    )
    notifier = Notifier("https://ntfy.sh", "coach-topic")
    proactive = ProactiveCoach(seeded, make_coach(seeded, claude), notifier, now=lambda: NOW)

    assert proactive.morning_checkin() == "You look recovered. Run the hills as planned."
    assert proactive.activity_feedback() == ["Good steady run."]
    assert proactive.activity_feedback() == []

    assert claude.requests[0]["output_config"] == {"effort": "low"}
    assert claude.requests[0]["model"] == "claude-haiku-5-5"
    assert "Scheduled morning check-in for Wednesday 28 October" in json.dumps(
        claude.requests[0]["messages"][-1]
    )
    assert [r.data.decode() for r in sent] == [
        "You look recovered. Run the hills as planned.",
        "Good steady run.",
    ]
    assert "title=Feedback%3A+Activity+1" in sent[1].full_url

    with seeded() as session:
        thread = session.scalars(select(Conversation).where(Conversation.kind == "coach")).one()
        assert thread.title == "Coach, week from 26 Oct 2026"
        items = chat_items(
            list(session.scalars(select(Message).where(Message.conversation_id == thread.id)))
        )
    assert [i.role for i in items] == ["event", "coach", "event", "coach"]
    assert items[0].text == "Morning check-in, 28 Oct"

    def make_service() -> SyncService:
        return SyncService(FakeGarmin([]), seeded, request_delay=0, sleep=lambda _: None)

    client = TestClient(single_app(seeded, make_service, make_coach(seeded, FakeClaude([]))))
    latest = client.get("/api/coach/latest").json()
    assert latest["text"] == "Good steady run."
    assert latest["label"] == "Feedback on Activity 1"


def test_a_new_week_starts_with_a_summary_of_last_week(
    seeded: sessionmaker[Session], sent: list[Any]
) -> None:
    claude = FakeClaude(
        [
            text_reply("Easy day."),
            text_reply("- Easy week, knee fine"),
            text_reply("Ready for hills."),
        ]
    )
    today = [NOW]
    coach = Coach(seeded, claude, SETTINGS, now=lambda: today[0])
    proactive = ProactiveCoach(
        seeded, coach, Notifier("https://ntfy.sh", None), now=lambda: today[0]
    )
    proactive.morning_checkin()
    today[0] = NOW + timedelta(days=7)
    proactive.morning_checkin()

    summary_request, checkin_request = claude.requests[1:]
    assert summary_request["messages"][-1]["content"][-1]["text"] == SUMMARY_PROMPT
    [turn] = checkin_request["messages"]
    assert turn["content"][0]["text"].endswith("- Easy week, knee fine")
    assert "Wednesday 04 November" in turn["content"][-1]["text"]

    with seeded() as session:
        threads = session.scalars(
            select(Conversation).where(Conversation.kind == "coach").order_by(Conversation.id)
        ).all()
        assert [t.title for t in threads] == [
            "Coach, week from 26 Oct 2026",
            "Coach, week from 02 Nov 2026",
        ]
        items = chat_items(
            list(session.scalars(select(Message).where(Message.conversation_id == threads[1].id)))
        )
    assert [i.role for i in items] == ["summary", "event", "coach"]


def test_failed_feedback_is_tried_again_on_the_next_sync(
    seeded: sessionmaker[Session], sent: list[Any]
) -> None:
    claude = FakeClaude([text_reply("Good steady run.")])
    coach = make_coach(seeded, claude, budget=0)
    proactive = ProactiveCoach(
        seeded, coach, Notifier("https://ntfy.sh", "coach-topic"), now=lambda: NOW
    )

    assert proactive.activity_feedback() == []
    assert claude.requests == []

    coach.settings = replace(SETTINGS, monthly_budget_usd=5.0)
    assert proactive.activity_feedback() == ["Good steady run."]
    assert proactive.activity_feedback() == []


def test_feedback_stops_after_three_failed_attempts(seeded: sessionmaker[Session]) -> None:
    coach = make_coach(seeded, FakeClaude([text_reply("Good steady run.")]), budget=0)
    proactive = ProactiveCoach(seeded, coach, Notifier("https://ntfy.sh", None), now=lambda: NOW)
    for _ in range(3):
        proactive.activity_feedback()

    coach.settings = replace(SETTINGS, monthly_budget_usd=5.0)
    assert proactive.activity_feedback() == []


def test_checkin_waits_for_last_nights_sleep(seeded: sessionmaker[Session]) -> None:
    claude = FakeClaude([text_reply("Slept well. Run as planned."), text_reply("No sleep data.")])
    tomorrow = NOW + timedelta(days=1)
    clock = {"now": tomorrow}
    coach = Coach(seeded, claude, SETTINGS, now=lambda: clock["now"])
    proactive = ProactiveCoach(
        seeded, coach, Notifier("https://ntfy.sh", None), now=lambda: clock["now"]
    )

    proactive.expect_checkin()
    proactive.after_sync()
    assert [r for r in claude.requests if "morning check-in" in json.dumps(r["messages"])] == []

    with seeded() as session:
        raw_store.put_daily(session, tomorrow.date(), "sleep", daily("sleep", tomorrow.date()))
        rebuild_all(session)
        session.commit()
    proactive.after_sync()
    checkins = [r for r in claude.requests if "morning check-in" in json.dumps(r["messages"])]
    assert len(checkins) == 1
    assert "has not uploaded last night" not in json.dumps(checkins[0]["messages"])
    assert proactive.checkin_deadline() is None


def test_checkin_goes_out_at_the_deadline_without_sleep_data(
    seeded: sessionmaker[Session],
) -> None:
    claude = FakeClaude([text_reply("No sleep data yet. Keep it easy.")])
    tomorrow = NOW + timedelta(days=1)
    coach = Coach(seeded, claude, SETTINGS, now=lambda: tomorrow)
    proactive = ProactiveCoach(
        seeded, coach, Notifier("https://ntfy.sh", None), now=lambda: tomorrow
    )
    with seeded() as session:
        session.add_all(
            ActivityFeedback(activity_id=activity_id, created_at=NOW) for activity_id in (1, 2)
        )
        session.commit()

    proactive.expect_checkin()
    proactive.after_sync()
    assert claude.requests == []

    assert proactive.checkin_deadline() == "No sleep data yet. Keep it easy."
    assert "has not uploaded last night" in json.dumps(claude.requests[0]["messages"])


def race_goal(sessions: sessionmaker[Session], day: date) -> None:
    with sessions() as session:
        session.add(Goal(kind="race", title="Mountain race", target_date=day))
        session.commit()


@pytest.mark.parametrize(
    ("days", "expected", "model"),
    [
        (10, "is in 10 days, so this is the taper", "claude-haiku-5-5"),
        (3, "write the race brief", SETTINGS.choice("review").model),
        (0, "the day of the race Mountain race", "claude-haiku-5-5"),
    ],
)
def test_checkin_changes_as_the_race_gets_close(
    seeded: sessionmaker[Session], days: int, expected: str, model: str
) -> None:
    race_goal(seeded, NOW.date() + timedelta(days=days))
    claude = FakeClaude([text_reply("Ready.")])
    proactive = ProactiveCoach(
        seeded, make_coach(seeded, claude), Notifier("https://ntfy.sh", None), now=lambda: NOW
    )
    proactive.morning_checkin()
    prompt = json.dumps(claude.requests[0]["messages"][-1])
    assert expected in prompt
    assert claude.requests[0]["model"] == model
    with seeded() as session:
        line = "Race day: Mountain race is today" if days == 0 else f"Mountain race in {days} days"
        assert line in context_block(session, NOW)


def test_activity_on_the_race_date_gets_a_race_review(seeded: sessionmaker[Session]) -> None:
    with seeded() as session:
        latest = session.scalars(
            select(Activity).order_by(Activity.start_time_local.desc())
        ).first()
        assert latest is not None
        race_day = latest.local_date
    race_goal(seeded, race_day)
    claude = FakeClaude([text_reply("Strong race.")])
    proactive = ProactiveCoach(
        seeded, make_coach(seeded, claude), Notifier("https://ntfy.sh", None), now=lambda: NOW
    )
    assert proactive.activity_feedback() == ["Strong race."]
    prompt = json.dumps(claude.requests[0]["messages"][-1])
    assert "Scheduled race review of activity" in prompt
    assert "Race lesson, Mountain race" in prompt
