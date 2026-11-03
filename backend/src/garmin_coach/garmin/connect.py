from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from garmin_coach.garmin.source import (
    GarminAuthError,
    GarminError,
    GarminNotFound,
    GarminRateLimited,
)

ACTIVITY_METHODS = {
    "splits": "get_activity_splits",
    "hr_zones": "get_activity_hr_in_timezones",
    "details": "get_activity_details",
    "exercise_sets": "get_activity_exercise_sets",
}

DAILY_METHODS = {
    "stats": "get_stats",
    "sleep": "get_sleep_data",
    "hrv": "get_hrv_data",
    "readiness": "get_training_readiness",
    "training_status": "get_training_status",
}


@contextmanager
def translated_errors() -> Iterator[None]:
    try:
        yield
    except GarminConnectTooManyRequestsError as e:
        raise GarminRateLimited(str(e)) from e
    except GarminConnectAuthenticationError as e:
        raise GarminAuthError(str(e)) from e
    except GarminConnectNotFoundError as e:
        raise GarminNotFound(str(e)) from e
    except GarminConnectConnectionError as e:
        raise GarminError(str(e)) from e


def prepare_tokens_dir(tokens_dir: Path) -> None:
    tokens_dir.mkdir(parents=True, exist_ok=True)
    tokens_dir.chmod(0o700)


def has_tokens(tokens_dir: Path) -> bool:
    return tokens_dir.is_dir() and any(tokens_dir.iterdir())


@dataclass
class PendingLogin:
    client: Garmin
    state: Any


class GarminWebLogin:
    """Logs in from a web form, where the two-step code arrives in a second request."""

    def start(self, tokens_dir: Path, email: str, password: str) -> PendingLogin | None:
        client = Garmin(email, password, return_on_mfa=True)
        with translated_errors():
            status, state = client.login()
        if status == "needs_mfa":
            return PendingLogin(client, state)
        self._save(client, tokens_dir)
        return None

    def finish(self, pending: PendingLogin, code: str, tokens_dir: Path) -> None:
        with translated_errors():
            pending.client.resume_login(pending.state, code)
        self._save(pending.client, tokens_dir)

    def _save(self, client: Garmin, tokens_dir: Path) -> None:
        prepare_tokens_dir(tokens_dir)
        client.client.dump(str(tokens_dir))
        GarminConnectSource(tokens_dir).login()


class GarminConnectSource:
    def __init__(
        self,
        tokens_dir: Path,
        email: str | None = None,
        password: str | None = None,
        prompt_mfa: Callable[[], str] | None = None,
    ) -> None:
        self.tokens_dir = tokens_dir
        self.email = email
        self.password = password
        self.prompt_mfa = prompt_mfa
        self._client: Garmin | None = None

    @property
    def client(self) -> Garmin:
        if self._client is None:
            self._client = self._login()
        return self._client

    def login(self) -> None:
        self._client = self._login()

    def _login(self) -> Garmin:
        prepare_tokens_dir(self.tokens_dir)
        client = Garmin(self.email, self.password, prompt_mfa=self.prompt_mfa)
        with translated_errors():
            client.login(str(self.tokens_dir))
        return client

    def list_activities(self, start: date, end: date) -> list[dict[str, Any]]:
        with translated_errors():
            result: list[dict[str, Any]] = self.client.get_activities_by_date(
                start.isoformat(), end.isoformat()
            )
        return result

    def activity_endpoint(self, activity_id: int, endpoint: str) -> Any:
        method = getattr(self.client, ACTIVITY_METHODS[endpoint])
        with translated_errors():
            return method(activity_id)

    def daily(self, kind: str, day: date) -> Any:
        method = getattr(self.client, DAILY_METHODS[kind])
        with translated_errors():
            return method(day.isoformat())

    def body_composition(self, start: date, end: date) -> Any:
        with translated_errors():
            return self.client.get_body_composition(start.isoformat(), end.isoformat())
