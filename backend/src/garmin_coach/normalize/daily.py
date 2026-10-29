import re
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from garmin_coach import raw_store
from garmin_coach.models import BodyComposition, DailyWellness

GRAMS_PER_KG = 1000
MORNING_READINESS_CONTEXT = "AFTER_WAKEUP_RESET"


def dig(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def training_status_label(phrase: str | None) -> str | None:
    if not phrase:
        return None
    return re.sub(r"_\d+$", "", phrase).replace("_", " ").capitalize()


def primary_device_entry(entries: dict[str, dict[str, Any]] | None) -> dict[str, Any] | None:
    if not entries:
        return None
    values = list(entries.values())
    return next((v for v in values if v.get("primaryTrainingDevice")), values[0])


def morning_readiness(readiness: Any) -> dict[str, Any] | None:
    if not isinstance(readiness, list) or not readiness:
        return None
    entries: list[dict[str, Any]] = readiness
    morning = [r for r in entries if r.get("inputContext") == MORNING_READINESS_CONTEXT]
    return min(morning or entries, key=lambda r: r.get("timestamp") or "")


def wellness_from_raw(day: date, raw: dict[str, Any]) -> DailyWellness:
    stats = raw.get("stats") or {}
    sleep = dig(raw.get("sleep"), "dailySleepDTO") or {}
    hrv = dig(raw.get("hrv"), "hrvSummary") or {}
    readiness = morning_readiness(raw.get("readiness")) or {}
    status_data = (
        primary_device_entry(
            dig(raw.get("training_status"), "mostRecentTrainingStatus", "latestTrainingStatusData")
        )
        or {}
    )
    status_phrase = status_data.get("trainingStatusFeedbackPhrase")

    return DailyWellness(
        day=day,
        steps=stats.get("totalSteps"),
        resting_hr=stats.get("restingHeartRate"),
        resting_hr_7d_avg=stats.get("lastSevenDaysAvgRestingHeartRate"),
        avg_stress=stats.get("averageStressLevel"),
        max_stress=stats.get("maxStressLevel"),
        body_battery_high=stats.get("bodyBatteryHighestValue"),
        body_battery_low=stats.get("bodyBatteryLowestValue"),
        body_battery_at_wake=stats.get("bodyBatteryAtWakeTime"),
        floors_ascended_m=stats.get("floorsAscendedInMeters"),
        sleep_s=sleep.get("sleepTimeSeconds"),
        deep_sleep_s=sleep.get("deepSleepSeconds"),
        light_sleep_s=sleep.get("lightSleepSeconds"),
        rem_sleep_s=sleep.get("remSleepSeconds"),
        awake_s=sleep.get("awakeSleepSeconds"),
        sleep_score=dig(sleep, "sleepScores", "overall", "value"),
        sleep_avg_hr=sleep.get("avgHeartRate"),
        sleep_avg_respiration=sleep.get("averageRespirationValue"),
        sleep_avg_stress=sleep.get("avgSleepStress"),
        hrv_last_night=hrv.get("lastNightAvg"),
        hrv_weekly_avg=hrv.get("weeklyAvg"),
        hrv_5min_high=hrv.get("lastNight5MinHigh"),
        hrv_status=hrv.get("status"),
        hrv_baseline_low=dig(hrv, "baseline", "balancedLow"),
        hrv_baseline_high=dig(hrv, "baseline", "balancedUpper"),
        readiness_score=readiness.get("score"),
        readiness_level=readiness.get("level"),
        readiness_feedback=readiness.get("feedbackShort"),
        acute_load=readiness.get("acuteLoad")
        or dig(status_data, "acuteTrainingLoadDTO", "dailyTrainingLoadAcute"),
        training_status=training_status_label(status_phrase),
        training_status_phrase=status_phrase,
        vo2max=dig(raw.get("training_status"), "mostRecentVO2Max", "generic", "vo2MaxPreciseValue"),
    )


def body_composition_entries(data: Any) -> list[BodyComposition]:
    entries = []
    for entry in dig(data, "dateWeightList") or []:
        calendar_date = entry.get("calendarDate")
        if calendar_date:
            day = date.fromisoformat(calendar_date)
        elif entry.get("date"):
            day = datetime.fromtimestamp(entry["date"] / 1000).date()
        else:
            continue
        weight = entry.get("weight")
        muscle = entry.get("muscleMass")
        entries.append(
            BodyComposition(
                day=day,
                weight_kg=None if weight is None else weight / GRAMS_PER_KG,
                body_fat_pct=entry.get("bodyFat"),
                muscle_mass_kg=None if muscle is None else muscle / GRAMS_PER_KG,
                bmi=entry.get("bmi"),
            )
        )
    return entries


def normalize_day(session: Session, day: date) -> DailyWellness:
    raw = {
        kind: raw_store.get_daily(session, day, kind)
        for kind in raw_store.daily_kinds(session, day)
    }
    for entry in body_composition_entries(raw.get("body_composition")):
        session.merge(entry)
    return session.merge(wellness_from_raw(day, raw))
