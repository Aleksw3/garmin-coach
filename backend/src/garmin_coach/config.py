from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    frontend_dir: Path = REPO_ROOT / "frontend" / "dist"
    garmin_email: str | None = None
    garmin_password: str | None = None
    garmin_request_delay: float = 2.0
    recent_sync_days: int = 14
    daily_refresh_days: int = 3
    trimp_coefficient: float = 1.92
    anthropic_api_key: str | None = None
    chat_model: str = "claude-sonnet-5-5"
    chat_effort: str = "low"
    monthly_budget_usd: float = 5.0

    @property
    def database_path(self) -> Path:
        return self.data_dir / "coach.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def garmin_tokens_dir(self) -> Path:
        return self.data_dir / "garmin_tokens"


@lru_cache
def get_settings() -> Settings:
    return Settings()
