import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.coach.agent import Coach, CoachError
from garmin_coach.coach.notify import Sender
from garmin_coach.models import Activity, ActivityFeedback, Conversation
from garmin_coach.reports import week_start

log = logging.getLogger(__name__)

MAX_FEEDBACK_PER_SYNC = 3

CHECKIN_PROMPT = """\
Scheduled morning check-in for {day:%A %d %B}. Look at last night's sleep, HRV and resting \
HR against the normal range, the recent load, and today's planned sessions. In at most 5 \
sentences, say how recovered I look and whether to do today's session as planned. If \
recovery clearly calls for a change, propose it with propose_changes and say so. If nothing \
is planned today, say what would fit."""

FEEDBACK_PROMPT = """\
Scheduled feedback on activity {id} ({name}, {start:%A %d %B %H:%M}). Read it with \
get_activity. Compare it with the planned session for that day if there is one, and with \
similar recent sessions. Start with your rating of the effort and the numbers behind it. In \
at most 6 sentences in total, say what went well, what to watch and anything to adjust in the \
next days. Use propose_changes only for a clear reason."""

REVIEW_PROMPT = """\
Scheduled weekly review for the week from {first} to {last}. Compare what I did with the \
plan, and look at load, recovery and progress toward my goals. Give a short table and a few \
sentences. Then check next week's plan. If it is missing or no longer fits, propose next \
week's sessions with propose_changes."""


class ProactiveCoach:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        coach: Coach,
        notifier: Sender,
        feedback_window: timedelta = timedelta(hours=36),
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.sessions = sessions
        self.coach = coach
        self.notifier = notifier
        self.feedback_window = feedback_window
        self.now = now

    def thread(self) -> int:
        title = f"Coach, week from {week_start(self.now().date()):%d %b %Y}"
        with self.sessions() as session:
            conversation = session.scalars(
                select(Conversation).where(
                    Conversation.kind == "coach", Conversation.title == title
                )
            ).first()
            if conversation is not None:
                return conversation.id
            last_week = session.scalars(
                select(Conversation)
                .where(Conversation.kind == "coach")
                .order_by(Conversation.created_at.desc(), Conversation.id.desc())
                .limit(1)
            ).first()
            now = self.now()
            conversation = Conversation(kind="coach", title=title, created_at=now, updated_at=now)
            session.add(conversation)
            session.commit()
            thread_id = conversation.id
            last_week_id = last_week.id if last_week else None
        if last_week_id is not None:
            try:
                self.coach.compact(last_week_id, into=thread_id, wait=True)
            except CoachError as error:
                log.warning("Could not carry last week's summary over: %s", error)
        return thread_id

    def _run(self, purpose: str, label: str, prompt: str, title: str) -> str | None:
        if not self.coach.ready:
            return None
        answer = ""
        for event in self.coach.reply(self.thread(), prompt, purpose, label=label, wait=True):
            if event["type"] == "text":
                answer += event["text"]
            elif event["type"] == "tool_call":
                answer = ""
            elif event["type"] == "error":
                log.error("%s failed: %s", label, event["message"])
                return None
        answer = answer.strip()
        if answer:
            self.notifier.send(title, answer)
        return answer or None

    def morning_checkin(self) -> str | None:
        day = self.now().date()
        return self._run(
            "checkin",
            f"Morning check-in, {day:%d %b}",
            CHECKIN_PROMPT.format(day=day),
            "Morning check-in",
        )

    def weekly_review(self) -> str | None:
        first = week_start(self.now().date())
        return self._run(
            "review",
            f"Weekly review, week from {first:%d %b}",
            REVIEW_PROMPT.format(first=first, last=first + timedelta(days=6)),
            "Weekly review",
        )

    def activity_feedback(self) -> list[str]:
        if not self.coach.ready:
            return []
        since = self.now() - self.feedback_window
        with self.sessions() as session:
            done = set(session.scalars(select(ActivityFeedback.activity_id)))
            activities = [
                activity
                for activity in session.scalars(
                    select(Activity)
                    .where(Activity.start_time_local >= since)
                    .order_by(Activity.start_time_local)
                )
                if not activity.is_commute and activity.id not in done
            ][:MAX_FEEDBACK_PER_SYNC]
            for activity in activities:
                session.add(ActivityFeedback(activity_id=activity.id, created_at=self.now()))
            session.commit()
        answers = []
        for activity in activities:
            name = activity.name or activity.type_key
            answer = self._run(
                "feedback",
                f"Feedback on {name}",
                FEEDBACK_PROMPT.format(id=activity.id, name=name, start=activity.start_time_local),
                f"Feedback: {name}",
            )
            if answer:
                answers.append(answer)
        return answers
