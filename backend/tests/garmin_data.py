from datetime import date, timedelta
from typing import Any

from garmin_coach.garmin.source import GarminError, GarminRateLimited


def activity_summary(
    activity_id: int,
    start_local: str,
    type_key: str = "running",
    distance_m: float = 10_000.0,
    duration_s: float = 3_600.0,
    elevation_gain_m: float = 300.0,
) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": f"Activity {activity_id}",
        "activityType": {"typeKey": type_key},
        "startTimeLocal": start_local,
        "startTimeGMT": start_local,
        "distance": distance_m,
        "duration": duration_s,
        "movingDuration": duration_s - 60,
        "elevationGain": elevation_gain_m,
        "elevationLoss": elevation_gain_m,
        "averageHR": 140.0,
        "maxHR": 165.0,
        "averageSpeed": distance_m / duration_s,
        "avgGradeAdjustedSpeed": distance_m / duration_s + 0.2,
        "activityTrainingLoad": 80.5,
        "aerobicTrainingEffect": 3.1,
        "anaerobicTrainingEffect": 0.4,
        "trainingEffectLabel": "AEROBIC_BASE",
        "startLatitude": 59.0,
        "startLongitude": 5.5,
        "endLatitude": 59.01,
        "endLongitude": 5.51,
        "lapCount": 2,
        "hrTimeInZone_1": 600.0,
        "hrTimeInZone_2": 2400.0,
        "hrTimeInZone_3": 600.0,
        "hrTimeInZone_4": 0.0,
        "hrTimeInZone_5": 0.0,
        "powerTimeInZone_1": 1800.0,
        "powerTimeInZone_2": 1800.0,
    }


def splits() -> dict[str, Any]:
    return {
        "lapDTOs": [
            {
                "lapIndex": 1,
                "startTimeGMT": "2026-10-20T08:00:00.0",
                "distance": 5000.0,
                "duration": 1800.0,
                "elevationGain": 200.0,
                "elevationLoss": 50.0,
                "averageHR": 135.0,
                "avgGradeAdjustedSpeed": 3.1,
                "intensityType": "INTERVAL",
            },
            {
                "lapIndex": 2,
                "startTimeGMT": "2026-10-20T08:30:00.0",
                "distance": 5000.0,
                "duration": 1800.0,
                "elevationGain": 100.0,
                "elevationLoss": 250.0,
            },
        ]
    }


def hr_zones() -> list[dict[str, Any]]:
    return [
        {"zoneNumber": zone, "secsInZone": 100.0 * zone, "zoneLowBoundary": 100 + 15 * zone}
        for zone in range(1, 6)
    ]


def exercise_sets() -> dict[str, Any]:
    return {
        "activityId": 1,
        "exerciseSets": [
            {
                "exercises": [{"category": "WARM_UP", "name": None, "probability": 99.0}],
                "repetitionCount": None,
                "weight": None,
                "setType": "ACTIVE",
                "messageIndex": 0,
            },
            {
                "exercises": [
                    {"category": "LUNGE", "name": "LUNGE", "probability": 20.0},
                    {"category": "SQUAT", "name": "BACK_SQUAT", "probability": 80.0},
                ],
                "repetitionCount": 6,
                "weight": 75000.0,
                "duration": 40.0,
                "setType": "ACTIVE",
                "startTime": "2026-10-06T15:42:58.0",
                "messageIndex": 1,
            },
            {"exercises": [], "setType": "REST", "duration": 120.0, "messageIndex": 2},
        ],
    }


def daily(kind: str, day: date) -> Any:
    iso = day.isoformat()
    match kind:
        case "stats":
            return {
                "calendarDate": iso,
                "totalSteps": 9000,
                "restingHeartRate": 43,
                "lastSevenDaysAvgRestingHeartRate": 42,
                "averageStressLevel": 25,
                "maxStressLevel": 90,
                "bodyBatteryHighestValue": 97,
                "bodyBatteryLowestValue": 25,
                "bodyBatteryAtWakeTime": 96,
                "floorsAscendedInMeters": 85.5,
            }
        case "sleep":
            return {
                "dailySleepDTO": {
                    "calendarDate": iso,
                    "sleepTimeSeconds": 28740,
                    "deepSleepSeconds": 6300,
                    "lightSleepSeconds": 16620,
                    "remSleepSeconds": 5820,
                    "awakeSleepSeconds": 360,
                    "avgHeartRate": 47.0,
                    "averageRespirationValue": 15.0,
                    "avgSleepStress": 13.0,
                    "sleepScores": {"overall": {"value": 93, "qualifierKey": "EXCELLENT"}},
                }
            }
        case "hrv":
            return {
                "hrvSummary": {
                    "calendarDate": iso,
                    "weeklyAvg": 66,
                    "lastNightAvg": 64,
                    "lastNight5MinHigh": 89,
                    "baseline": {"lowUpper": 67, "balancedLow": 69, "balancedUpper": 79},
                    "status": "LOW",
                }
            }
        case "readiness":
            return [
                {
                    "calendarDate": iso,
                    "timestamp": f"{iso}T12:00:00.0",
                    "inputContext": "AFTER_ACTIVITY",
                    "score": 40,
                    "level": "LOW",
                },
                {
                    "calendarDate": iso,
                    "timestamp": f"{iso}T05:55:12.0",
                    "inputContext": "AFTER_WAKEUP_RESET",
                    "score": 72,
                    "level": "MODERATE",
                    "feedbackShort": "LISTEN_TO_YOUR_BODY",
                    "acuteLoad": 261,
                },
            ]
        case "training_status":
            return {
                "mostRecentVO2Max": {"generic": {"vo2MaxPreciseValue": 55.3}},
                "mostRecentTrainingStatus": {
                    "latestTrainingStatusData": {
                        "123": {
                            "calendarDate": iso,
                            "trainingStatusFeedbackPhrase": "STRAINED_4",
                            "primaryTrainingDevice": True,
                        }
                    }
                },
            }
    raise ValueError(kind)


class FakeGarmin:
    def __init__(self, activities: list[dict[str, Any]]) -> None:
        self.activities = activities
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.rate_limit_after: int | None = None
        self.failing: set[tuple[str, tuple[Any, ...]]] = set()
        self.workouts: dict[int, dict[str, Any]] = {}

    def _record(self, name: str, *args: Any) -> None:
        if self.rate_limit_after is not None and len(self.calls) >= self.rate_limit_after:
            raise GarminRateLimited("429")
        self.calls.append((name, args))
        if (name, args) in self.failing:
            raise GarminError("500")

    def list_activities(self, start: date, end: date) -> list[dict[str, Any]]:
        self._record("list", start, end)
        return [
            a
            for a in self.activities
            if start <= date.fromisoformat(a["startTimeLocal"][:10]) <= end
        ]

    def activity_endpoint(self, activity_id: int, endpoint: str) -> Any:
        self._record("activity", activity_id, endpoint)
        if endpoint == "weather":
            return {"temp": 50, "apparentTemp": 41, "relativeHumidity": 80}
        return {"splits": splits, "hr_zones": hr_zones, "details": dict}.get(
            endpoint, exercise_sets
        )()

    def daily(self, kind: str, day: date) -> Any:
        self._record("daily", kind, day)
        return daily(kind, day)

    def body_composition(self, start: date, end: date) -> Any:
        self._record("body_composition", start, end)
        return {
            "dateWeightList": [
                {"calendarDate": end.isoformat(), "weight": 72500.0, "bodyFat": 12.5}
            ]
        }

    def upload_workout(self, workout: dict[str, Any]) -> int:
        self._record("upload_workout", workout["workoutName"])
        workout_id = 100 + len(self.calls)
        self.workouts[workout_id] = workout
        return workout_id

    def schedule_workout(self, workout_id: int, day: date) -> int | None:
        self._record("schedule_workout", workout_id, day)
        return workout_id + 1000

    def unschedule_workout(self, schedule_id: int) -> None:
        self._record("unschedule_workout", schedule_id)

    def delete_workout(self, workout_id: int) -> None:
        self._record("delete_workout", workout_id)
        self.workouts.pop(workout_id, None)

    def count(self, name: str) -> int:
        return sum(1 for call_name, _ in self.calls if call_name == name)


def days_back(today: date, days: int) -> date:
    return today - timedelta(days=days)
