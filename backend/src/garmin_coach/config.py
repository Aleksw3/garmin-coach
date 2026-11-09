from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    frontend_dir: Path = REPO_ROOT / "frontend" / "dist"
    garmin_request_delay: float = 2.0
    recent_sync_days: int = 14
    daily_refresh_days: int = 3
    trimp_coefficient: float = 1.92
    anthropic_api_key: str | None = None
    chat_model: str = "claude-sonnet-5-5"
    chat_effort: str = "low"
    plan_model: str = "claude-opus-5-5"
    plan_effort: str = "high"
    background_model: str = "claude-haiku-5-5"
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic: str | None = None
    ntfy_token: str | None = None
    app_url: str | None = None
    checkin_time: str = "06:30"
    review_day: str = "sun"
    review_time: str = "19:00"
    watch_time: str = "20:00"
    feedback_window_hours: int = 36
    evidence_day: str = "mon"
    evidence_time: str = "07:00"
    monthly_budget_usd: float = 5.0

    @property
    def single_database_path(self) -> Path:
        return self.data_dir / "coach.db"

    @property
    def single_tokens_dir(self) -> Path:
        return self.data_dir / "garmin_tokens"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def research_database_path(self) -> Path:
        return self.data_dir / "research.db"

    def profile_dir(self, slug: str) -> Path:
        return self.profiles_dir / slug

    def profile_database_path(self, slug: str) -> Path:
        return self.profile_dir(slug) / "coach.db"

    def profile_tokens_dir(self, slug: str) -> Path:
        return self.profile_dir(slug) / "garmin_tokens"


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
