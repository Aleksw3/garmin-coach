import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

MAX_BODY_CHARS = 3500
TIMEOUT_S = 10


@dataclass(frozen=True)
class Notifier:
    url: str
    topic: str | None
    token: str | None = None
    app_url: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.topic)

    def send(self, title: str, message: str, page: str = "#chat") -> bool:
        if not self.topic:
            return False
        params = {"title": title, "markdown": "yes"}
        if self.app_url:
            params["click"] = self.app_url.rstrip("/") + "/" + page
        body = message if len(message) <= MAX_BODY_CHARS else message[:MAX_BODY_CHARS] + "…"
        request = urllib.request.Request(
            f"{self.url.rstrip('/')}/{urllib.parse.quote(self.topic)}?{urllib.parse.urlencode(params)}",
            data=body.encode(),
            method="POST",
        )
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S):
                return True
        except (urllib.error.URLError, TimeoutError):
            log.exception("Sending the ntfy notification failed")
            return False


NO_NOTIFIER = Notifier("https://ntfy.sh", None)
