from dataclasses import dataclass
from typing import Literal

import anthropic
from sqlalchemy.orm import Session

from garmin_coach.config import Settings
from garmin_coach.sync import get_state, set_state

API_KEY = "anthropic_api_key"
MONTHLY_BUDGET = "monthly_budget_usd"
KEY_CHECK_TIMEOUT_S = 15


class InvalidApiKey(ValueError):
    pass


@dataclass(frozen=True)
class ClaudeSettings:
    api_key: str | None
    monthly_budget_usd: float
    source: Literal["app", "env"] | None

    @property
    def key_hint(self) -> str | None:
        return self.api_key[-4:] if self.api_key else None


def read_claude_settings(session: Session, settings: Settings) -> ClaudeSettings:
    saved_key = get_state(session, API_KEY)
    saved_budget = get_state(session, MONTHLY_BUDGET)
    key = saved_key or settings.anthropic_api_key or None
    return ClaudeSettings(
        api_key=key,
        monthly_budget_usd=float(saved_budget) if saved_budget else settings.monthly_budget_usd,
        source="app" if saved_key else "env" if key else None,
    )


def save_claude_settings(
    session: Session, api_key: str | None = None, monthly_budget_usd: float | None = None
) -> None:
    if api_key is not None:
        set_state(session, API_KEY, api_key)
    if monthly_budget_usd is not None:
        set_state(session, MONTHLY_BUDGET, str(monthly_budget_usd))
    session.commit()


def check_api_key(api_key: str) -> None:
    client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=KEY_CHECK_TIMEOUT_S)
    try:
        client.models.list(limit=1)
    except anthropic.AuthenticationError as error:
        raise InvalidApiKey(
            "Anthropic rejected the key. Check that you copied all of it."
        ) from error
    except anthropic.PermissionDeniedError as error:
        raise InvalidApiKey("The key has no access to the API. Check it in the console.") from error
    except anthropic.APIConnectionError as error:
        raise InvalidApiKey("Could not reach Anthropic. Check the internet connection.") from error
