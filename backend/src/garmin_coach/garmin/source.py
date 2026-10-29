from datetime import date
from typing import Any, Protocol

ACTIVITY_ENDPOINTS = ("splits", "hr_zones", "details")
STRENGTH_ENDPOINTS = ("exercise_sets",)
DAILY_KINDS = ("stats", "sleep", "hrv", "readiness", "training_status")


class GarminError(Exception):
    pass


class GarminAuthError(GarminError):
    pass


class GarminRateLimited(GarminError):
    pass


class GarminNotFound(GarminError):
    pass


class GarminSource(Protocol):
    def list_activities(self, start: date, end: date) -> list[dict[str, Any]]: ...

    def activity_endpoint(self, activity_id: int, endpoint: str) -> Any: ...

    def daily(self, kind: str, day: date) -> Any: ...

    def body_composition(self, start: date, end: date) -> Any: ...
