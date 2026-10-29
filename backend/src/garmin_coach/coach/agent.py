import json
import logging
import threading
from collections.abc import Callable, Generator, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.prompt import SYSTEM_PROMPT, context_block
from garmin_coach.coach.tools import ToolContext, run_tool, tool_definitions
from garmin_coach.coach.usage import month_spend, record_usage
from garmin_coach.models import Conversation, Message

log = logging.getLogger(__name__)

THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
MAX_TOKENS = 16000
MAX_ROUNDS = 10
MAX_PARSE_RETRIES = 2
TITLE_LENGTH = 60

SYSTEM = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
TOOL_DEFINITIONS = tool_definitions()

Event = dict[str, Any]
StreamFactory = Callable[..., AbstractContextManager[Any]]


def anthropic_stream_factory(api_key: str) -> StreamFactory:
    return anthropic.Anthropic(api_key=api_key).beta.messages.stream


@dataclass(frozen=True)
class CoachSettings:
    model: str
    effort: str
    monthly_budget_usd: float
    trimp_coefficient: float


def title_from(text: str) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else "New conversation"
    if len(first_line) <= TITLE_LENGTH:
        return first_line
    return first_line[: TITLE_LENGTH - 3].rstrip() + "..."


def error(message: str) -> Event:
    return {"type": "error", "message": message}


class Coach:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        stream_factory: StreamFactory | None,
        settings: CoachSettings,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.sessions = sessions
        self.stream_factory = stream_factory
        self.settings = settings
        self.now = now
        self._lock = threading.Lock()

    def reply(self, conversation_id: int, text: str) -> Iterator[Event]:
        if self.stream_factory is None:
            yield error("No Anthropic API key. Set ANTHROPIC_API_KEY in .env and restart.")
            return
        if not self._lock.acquire(blocking=False):
            yield error("The coach is already answering. Wait for that reply to finish.")
            return
        try:
            yield from self._reply(conversation_id, text)
        finally:
            self._lock.release()

    def _save(
        self,
        session: Session,
        conversation_id: int,
        role: str,
        content: list[dict[str, Any]],
        display_text: str | None = None,
    ) -> None:
        now = self.now()
        session.add(
            Message(
                conversation_id=conversation_id,
                role=role,
                content=json.dumps(content, ensure_ascii=False),
                display_text=display_text,
                created_at=now,
            )
        )
        conversation = session.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = now

    def _start_turn(self, conversation_id: int, text: str) -> list[dict[str, Any]] | str:
        now = self.now()
        with self.sessions() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return f"No conversation with id {conversation_id}"
            spent = month_spend(session, now.date())
            budget = self.settings.monthly_budget_usd
            if spent >= budget:
                return (
                    f"This month's API budget of ${budget:.2f} is used up (${spent:.2f} spent). "
                    "Chat opens again on the 1st, or raise MONTHLY_BUDGET_USD in .env."
                )
            history = [
                {"role": message.role, "content": json.loads(message.content)}
                for message in session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.id)
                )
            ]
            content = [
                {"type": "text", "text": context_block(session, now)},
                {"type": "text", "text": text},
            ]
            self._save(session, conversation_id, "user", content, display_text=text)
            if conversation.title is None:
                conversation.title = title_from(text)
            session.commit()
        return [*history, {"role": "user", "content": content}]

    def _stream(self, history: list[dict[str, Any]]) -> Generator[Event, None, Any]:
        assert self.stream_factory is not None
        with self.stream_factory(
            model=self.settings.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            tools=TOOL_DEFINITIONS,
            messages=history,
            thinking={
                "type": "adaptive",
                "block_binding": {"prefix_mismatch_behavior": "drop_block"},
            },
            output_config={"effort": self.settings.effort},
            cache_control={"type": "ephemeral"},
            betas=[THINKING_BINDING_BETA],
        ) as stream:
            for event in stream:
                if event.type == "text":
                    yield {"type": "text", "text": event.text}
            return stream.get_final_message()

    def _call_model(self, history: list[dict[str, Any]]) -> Generator[Event, None, Any]:
        for attempt in range(MAX_PARSE_RETRIES + 1):
            try:
                return (yield from self._stream(history))
            except ValueError:
                log.warning("Unparseable tool input, attempt %d", attempt + 1)
        return None

    def _reply(self, conversation_id: int, text: str) -> Iterator[Event]:
        started = self._start_turn(conversation_id, text)
        if isinstance(started, str):
            yield error(started)
            return
        history = started
        turn_cost = 0.0
        for _ in range(MAX_ROUNDS):
            try:
                message = yield from self._call_model(history)
            except anthropic.APIError as api_error:
                log.exception("Claude API call failed")
                yield error(f"The Claude API call failed: {api_error}")
                return
            if message is None:
                yield error("The coach sent a tool call that could not be read. Try again.")
                return

            content = [
                block.model_dump(mode="json", exclude_none=True) for block in message.content
            ]
            with self.sessions() as session:
                usage = record_usage(
                    session, self.settings.model, "chat", conversation_id, message.usage
                )
                self._save(session, conversation_id, "assistant", content)
                session.commit()
            turn_cost += usage.cost_usd
            history.append({"role": "assistant", "content": content})

            if message.stop_reason == "refusal":
                yield error("The model declined to answer this. Try rephrasing the question.")
                break
            tool_uses = [block for block in message.content if block.type == "tool_use"]
            if not tool_uses:
                break
            results = []
            with self.sessions() as session:
                context = ToolContext(session, self.now().date(), self.settings.trimp_coefficient)
                for block in tool_uses:
                    yield {
                        "type": "tool_call",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                    if message.stop_reason == "max_tokens":
                        output, ok = "The tool input was cut off by the output limit.", False
                    else:
                        output, ok = run_tool(context, block.name, block.input)
                    yield {"type": "tool_result", "id": block.id, "ok": ok}
                    result = {"type": "tool_result", "tool_use_id": block.id, "content": output}
                    results.append(result if ok else {**result, "is_error": True})
                self._save(session, conversation_id, "user", results)
                session.commit()
            history.append({"role": "user", "content": results})
        else:
            yield error(f"The coach stopped after {MAX_ROUNDS} rounds of tool calls.")

        with self.sessions() as session:
            spent = month_spend(session, self.now().date())
        yield {
            "type": "done",
            "turn_cost_usd": turn_cost,
            "month_cost_usd": spent,
            "budget_usd": self.settings.monthly_budget_usd,
        }
