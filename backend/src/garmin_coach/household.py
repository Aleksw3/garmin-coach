from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import Any

import anthropic
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach.api.profile import ProfileRuntime, make_profile
from garmin_coach.claude_settings import ClaudeSettings, read_claude_settings, save_claude_settings
from garmin_coach.coach.agent import Coach, StreamFactory, anthropic_stream_factory, coach_settings
from garmin_coach.coach.notify import Notifier, ProfileNotifier
from garmin_coach.coach.proactive import ProactiveCoach
from garmin_coach.coach.usage import Spending
from garmin_coach.config import Settings
from garmin_coach.evidence.fetch import EvidenceFetcher
from garmin_coach.evidence.pubmed import PubMed
from garmin_coach.evidence.summarize import Summarizer
from garmin_coach.profiles import athlete, create_profile, open_profile, profile_slugs, slug_for
from garmin_coach.sync import SyncService

MakeSyncService = Callable[[str, sessionmaker[Session]], SyncService]


class Household:
    def __init__(
        self,
        settings: Settings,
        research: sessionmaker[Session],
        make_sync_service: MakeSyncService,
        pubmed: PubMed | None = None,
    ) -> None:
        self.settings = settings
        self.research = research
        self.make_sync_service = make_sync_service
        self.spending = Spending([research])
        self.notifier = Notifier(settings.ntfy_url, None, settings.ntfy_token, settings.app_url)
        self.profiles: dict[str, ProfileRuntime] = {}
        with research() as session:
            self.claude = read_claude_settings(session, settings)
        self.fetcher = EvidenceFetcher(
            research,
            pubmed or PubMed(),
            Summarizer(self._messages_create(), settings.background_model),
            self.claude.monthly_budget_usd,
            spending=self.spending,
        )

    def _stream_factory(self) -> StreamFactory | None:
        key = self.claude.api_key
        return anthropic_stream_factory(key) if key else None

    def _messages_create(self) -> Callable[..., Any] | None:
        key = self.claude.api_key
        return anthropic.Anthropic(api_key=key).messages.create if key else None

    def open_all(self) -> list[ProfileRuntime]:
        return [self.open(slug) for slug in profile_slugs(self.settings)]

    def open(self, slug: str) -> ProfileRuntime:
        sessions = open_profile(self.settings, slug)
        self.spending.sources.append(sessions)

        def read_topic() -> str | None:
            with sessions() as session:
                return athlete(session).ntfy_topic

        coach = Coach(
            sessions,
            self._stream_factory(),
            replace(
                coach_settings(self.settings), monthly_budget_usd=self.claude.monthly_budget_usd
            ),
            research=self.research,
            spending=self.spending,
        )
        notifier = ProfileNotifier(self.notifier, slug, read_topic)
        window = timedelta(hours=self.settings.feedback_window_hours)
        proactive = ProactiveCoach(sessions, coach, notifier, window)
        runtime = make_profile(
            slug,
            sessions,
            lambda: self.make_sync_service(slug, sessions),
            coach,
            proactive,
            notifier,
        )
        self.profiles[slug] = runtime
        return runtime

    def add(self, name: str, trimp: float) -> ProfileRuntime:
        slug = slug_for(name, set(profile_slugs(self.settings)))
        create_profile(self.settings, slug, name, trimp)
        return self.open(slug)

    def update_claude(
        self, api_key: str | None = None, monthly_budget_usd: float | None = None
    ) -> ClaudeSettings:
        with self.research() as session:
            save_claude_settings(session, api_key, monthly_budget_usd)
            self.claude = read_claude_settings(session, self.settings)
        stream_factory = self._stream_factory()
        budget = self.claude.monthly_budget_usd
        for profile in self.profiles.values():
            profile.coach.stream_factory = stream_factory
            profile.coach.settings = replace(profile.coach.settings, monthly_budget_usd=budget)
        self.fetcher.summarizer.create = self._messages_create()
        self.fetcher.monthly_budget_usd = budget
        return self.claude
