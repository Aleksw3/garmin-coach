import json
import logging
import threading
from collections.abc import Callable, Generator, Iterator
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.prompt import SYSTEM_PROMPT, context_block
from garmin_coach.coach.tools import ToolContext, run_tool, tool_definitions
from garmin_coach.coach.usage import Spending, record_usage
from garmin_coach.config import Settings
from garmin_coach.metrics.load import trimp_for
from garmin_coach.models import Conversation, Message

log = logging.getLogger(__name__)

THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
MAX_ROUNDS = 10
MAX_PARSE_RETRIES = 2
TITLE_LENGTH = 200
LOCK_WAIT_S = 900

SYSTEM = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
TOOL_DEFINITIONS = tool_definitions()

SUMMARY_PROMPT = """\
Summarize this conversation so a new one can continue from the summary alone. Keep what I \
told you about how I feel, sleep and recover, injuries and niggles, decisions we made, plan \
changes you proposed and whether I accepted them, and questions that are still open. Leave \
out numbers you can look up again with the tools. Write at most 250 words as short bullet \
points under a few plain headings. Do not call any tools."""
SUMMARY_INTRO = "Summary of the earlier conversation:\n\n"

Event = dict[str, Any]
StreamFactory = Callable[..., AbstractContextManager[Any]]


def anthropic_stream_factory(api_key: str) -> StreamFactory:
    return anthropic.Anthropic(api_key=api_key).beta.messages.stream


@dataclass(frozen=True)
class ModelChoice:
    model: str
    effort: str
    max_tokens: int = 16000


@dataclass(frozen=True)
class CoachSettings:
    models: dict[str, ModelChoice]
    monthly_budget_usd: float
    trimp_coefficient: float

    def choice(self, purpose: str) -> ModelChoice:
        return self.models.get(purpose, self.models["chat"])


def coach_settings(settings: Settings) -> CoachSettings:
    background = ModelChoice(settings.background_model, "low", 8000)
    return CoachSettings(
        models={
            "chat": ModelChoice(settings.chat_model, settings.chat_effort),
            "plan": ModelChoice(settings.plan_model, settings.plan_effort, 32000),
            "review": ModelChoice(settings.chat_model, "medium"),
            "checkin": background,
            "feedback": background,
            "summary": background,
        },
        monthly_budget_usd=settings.monthly_budget_usd,
        trimp_coefficient=settings.trimp_coefficient,
    )


def title_from(text: str) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else "New conversation"
    if len(first_line) <= TITLE_LENGTH:
        return first_line
    return first_line[: TITLE_LENGTH - 3].rstrip() + "..."


def error(message: str) -> Event:
    return {"type": "error", "message": message}


class CoachError(Exception):
    pass


def append_turn(history: list[dict[str, Any]], role: str, content: list[dict[str, Any]]) -> None:
    if history and history[-1]["role"] == role:
        history[-1]["content"] = [*history[-1]["content"], *content]
    else:
        history.append({"role": role, "content": content})


def since_summary(session: Session, conversation_id: int) -> list[Message]:
    messages = session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    ).all()
    summaries = [index for index, message in enumerate(messages) if message.source == "summary"]
    return list(messages[summaries[-1] :] if summaries else messages)


def model_history(messages: list[Message]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for message in messages:
        append_turn(history, message.role, json.loads(message.content))
    return history


def final_value(generator: Generator[Event, None, Any]) -> Any:
    while True:
        try:
            next(generator)
        except StopIteration as stop:
            return stop.value


class Coach:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        stream_factory: StreamFactory | None,
        settings: CoachSettings,
        now: Callable[[], datetime] = datetime.now,
        research: sessionmaker[Session] | None = None,
        spending: Spending | None = None,
    ) -> None:
        self.sessions = sessions
        self.research = research
        self.spending = spending or Spending([sessions])
        self.stream_factory = stream_factory
        self.settings = settings
        self.now = now
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.stream_factory is not None

    def research_session(self) -> AbstractContextManager[Session | None]:
        return nullcontext() if self.research is None else self.research()

    def reply(
        self,
        conversation_id: int,
        text: str,
        purpose: str = "chat",
        label: str | None = None,
        wait: bool = False,
    ) -> Iterator[Event]:
        if self.stream_factory is None:
            yield error("No Anthropic API key yet. Add one on the Settings page.")
            return
        if not self._lock.acquire(timeout=LOCK_WAIT_S if wait else 0):
            yield error("The coach is already answering. Wait for that reply to finish.")
            return
        try:
            yield from self._reply(conversation_id, text, purpose, label)
        finally:
            self._lock.release()

    def _save(
        self,
        session: Session,
        conversation_id: int,
        role: str,
        content: list[dict[str, Any]],
        display_text: str | None = None,
        source: str = "user",
    ) -> None:
        now = self.now()
        session.add(
            Message(
                conversation_id=conversation_id,
                role=role,
                content=json.dumps(content, ensure_ascii=False),
                display_text=display_text,
                source=source,
                created_at=now,
            )
        )
        conversation = session.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = now

    def _budget_used_up(self) -> str | None:
        spent = self.spending(self.now().date())
        budget = self.settings.monthly_budget_usd
        if spent < budget:
            return None
        return (
            f"This month's API budget of ${budget:.2f} is used up (${spent:.2f} spent). "
            "Chat opens again on the 1st, or raise MONTHLY_BUDGET_USD in .env."
        )

    def _start_turn(
        self, conversation_id: int, text: str, label: str | None
    ) -> list[dict[str, Any]] | str:
        now = self.now()
        with self.sessions() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return f"No conversation with id {conversation_id}"
            if used_up := self._budget_used_up():
                return used_up
            history = model_history(since_summary(session, conversation_id))
            content = [
                {"type": "text", "text": context_block(session, now)},
                {"type": "text", "text": text},
            ]
            if label is None:
                self._save(session, conversation_id, "user", content, display_text=text)
            else:
                self._save(session, conversation_id, "user", content, label, source="schedule")
            if conversation.title is None:
                conversation.title = title_from(text)
            session.commit()
        append_turn(history, "user", content)
        return history

    def compact(self, conversation_id: int, into: int | None = None, wait: bool = False) -> str:
        if self.stream_factory is None:
            raise CoachError("No Anthropic API key yet. Add one on the Settings page.")
        if not self._lock.acquire(timeout=LOCK_WAIT_S if wait else 0):
            raise CoachError("The coach is already answering. Wait for that reply to finish.")
        target = into or conversation_id
        try:
            summary = self._summarize(conversation_id, target)
            with self.sessions() as session:
                self._save(
                    session,
                    target,
                    "user",
                    [{"type": "text", "text": SUMMARY_INTRO + summary}],
                    display_text=summary,
                    source="summary",
                )
                session.commit()
            return summary
        finally:
            self._lock.release()

    def _summarize(self, conversation_id: int, target: int) -> str:
        with self.sessions() as session:
            messages = since_summary(session, conversation_id)
        if not messages:
            raise CoachError("This conversation has no messages yet.")
        if len(messages) == 1 and messages[0].source == "summary":
            if target != conversation_id and messages[0].display_text:
                return messages[0].display_text
            raise CoachError("Nothing new to compact since the last summary.")
        if used_up := self._budget_used_up():
            raise CoachError(used_up)

        history = model_history(messages)
        append_turn(history, "user", [{"type": "text", "text": SUMMARY_PROMPT}])
        choice = self.settings.choice("summary")
        try:
            message = final_value(self._call_model(history, choice, {"type": "none"}))
        except anthropic.APIError as api_error:
            log.exception("Claude API call for a summary failed")
            raise CoachError(f"The Claude API call failed: {api_error}") from api_error
        if message is None or message.stop_reason == "refusal":
            raise CoachError("The coach could not summarize this conversation. Try again.")
        with self.sessions() as session:
            record_usage(session, choice.model, "summary", target, message.usage)
            session.commit()
        summary = "\n\n".join(block.text for block in message.content if block.type == "text")
        if not summary.strip():
            raise CoachError("The coach returned an empty summary. Try again.")
        return summary.strip()

    def _stream(
        self,
        history: list[dict[str, Any]],
        choice: ModelChoice,
        tool_choice: dict[str, str] | None = None,
    ) -> Generator[Event, None, Any]:
        assert self.stream_factory is not None
        extra = {} if tool_choice is None else {"tool_choice": tool_choice}
        with self.stream_factory(
            model=choice.model,
            max_tokens=choice.max_tokens,
            system=SYSTEM,
            tools=TOOL_DEFINITIONS,
            messages=history,
            thinking={
                "type": "adaptive",
                "block_binding": {"prefix_mismatch_behavior": "drop_block"},
            },
            output_config={"effort": choice.effort},
            cache_control={"type": "ephemeral"},
            betas=[THINKING_BINDING_BETA],
            **extra,
        ) as stream:
            for event in stream:
                if event.type == "text":
                    yield {"type": "text", "text": event.text}
            return stream.get_final_message()

    def _call_model(
        self,
        history: list[dict[str, Any]],
        choice: ModelChoice,
        tool_choice: dict[str, str] | None = None,
    ) -> Generator[Event, None, Any]:
        for attempt in range(MAX_PARSE_RETRIES + 1):
            try:
                return (yield from self._stream(history, choice, tool_choice))
            except ValueError:
                log.warning("Unparseable tool input, attempt %d", attempt + 1)
        return None

    def _reply(
        self, conversation_id: int, text: str, purpose: str, label: str | None
    ) -> Iterator[Event]:
        choice = self.settings.choice(purpose)
        started = self._start_turn(conversation_id, text, label)
        if isinstance(started, str):
            yield error(started)
            return
        history = started
        turn_cost = 0.0
        for _ in range(MAX_ROUNDS):
            try:
                message = yield from self._call_model(history, choice)
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
                usage = record_usage(session, choice.model, purpose, conversation_id, message.usage)
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
            with self.sessions() as session, self.research_session() as research:
                context = ToolContext(
                    session,
                    self.now(),
                    trimp_for(session, self.settings.trimp_coefficient),
                    conversation_id,
                    research,
                )
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
            append_turn(history, "user", results)
        else:
            yield error(f"The coach stopped after {MAX_ROUNDS} rounds of tool calls.")

        spent = self.spending(self.now().date())
        yield {
            "type": "done",
            "turn_cost_usd": turn_cost,
            "month_cost_usd": spent,
            "budget_usd": self.settings.monthly_budget_usd,
        }
