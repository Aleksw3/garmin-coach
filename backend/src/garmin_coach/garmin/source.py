from datetime import date
from typing import Any, Protocol

ACTIVITY_ENDPOINTS = ("splits", "hr_zones", "details")
STRENGTH_ENDPOINTS = ("exercise_sets",)
WEATHER_ENDPOINTS = ("weather",)
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

    def upload_workout(self, workout: dict[str, Any]) -> int: ...

    def schedule_workout(self, workout_id: int, day: date) -> int | None: ...

    def unschedule_workout(self, schedule_id: int) -> None: ...

    def delete_workout(self, workout_id: int) -> None: ...
