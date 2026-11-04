from datetime import datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from garmin_coach import raw_store
from garmin_coach.metrics.heart_rate import drift, histogram, samples
from garmin_coach.models import (
    Activity,
    ActivityHeartRate,
    ActivityLap,
    ActivityZoneTime,
    Climb,
    StrengthSet,
)
from garmin_coach.normalize.climbs import store_climbs
from garmin_coach.normalize.sports import sport_groups

GRAMS_PER_KG = 1000
ZONE_COUNT = 5


def parse_time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def activity_from_summary(summary: dict[str, Any]) -> Activity:
    start_local = datetime.fromisoformat(summary["startTimeLocal"])
    return Activity(
        id=summary["activityId"],
        name=summary.get("activityName"),
        type_key=summary["activityType"]["typeKey"],
        start_time_local=start_local,
        start_time_gmt=datetime.fromisoformat(summary["startTimeGMT"]),
        local_date=start_local.date(),
        duration_s=summary.get("duration"),
        moving_s=summary.get("movingDuration"),
        distance_m=summary.get("distance"),
        elevation_gain_m=summary.get("elevationGain"),
        elevation_loss_m=summary.get("elevationLoss"),
        min_elevation_m=summary.get("minElevation"),
        max_elevation_m=summary.get("maxElevation"),
        avg_hr=summary.get("averageHR"),
        max_hr=summary.get("maxHR"),
        avg_speed_mps=summary.get("averageSpeed"),
        avg_grade_adjusted_speed_mps=summary.get("avgGradeAdjustedSpeed"),
        avg_power_w=summary.get("avgPower"),
        normalized_power_w=summary.get("normPower"),
        calories=summary.get("calories"),
        training_load=summary.get("activityTrainingLoad"),
        aerobic_training_effect=summary.get("aerobicTrainingEffect"),
        anaerobic_training_effect=summary.get("anaerobicTrainingEffect"),
        training_effect_label=summary.get("trainingEffectLabel"),
        vo2max=summary.get("vO2MaxValue"),
        start_lat=summary.get("startLatitude"),
        start_lon=summary.get("startLongitude"),
        end_lat=summary.get("endLatitude"),
        end_lon=summary.get("endLongitude"),
        location_name=summary.get("locationName"),
        lap_count=summary.get("lapCount"),
    )


def laps_from_splits(activity_id: int, splits: dict[str, Any]) -> list[ActivityLap]:
    return [
        ActivityLap(
            activity_id=activity_id,
            lap_index=lap.get("lapIndex", position + 1),
            start_time_gmt=parse_time(lap.get("startTimeGMT")),
            distance_m=lap.get("distance"),
            duration_s=lap.get("duration"),
            moving_s=lap.get("movingDuration"),
            elevation_gain_m=lap.get("elevationGain"),
            elevation_loss_m=lap.get("elevationLoss"),
            avg_hr=lap.get("averageHR"),
            max_hr=lap.get("maxHR"),
            avg_speed_mps=lap.get("averageSpeed"),
            avg_grade_adjusted_speed_mps=lap.get("avgGradeAdjustedSpeed"),
            avg_power_w=lap.get("averagePower"),
            intensity_type=lap.get("intensityType"),
        )
        for position, lap in enumerate(splits.get("lapDTOs") or [])
    ]


def zones_from_summary(
    activity_id: int, summary: dict[str, Any], hr_zones: list[dict[str, Any]] | None
) -> list[ActivityZoneTime]:
    zones = []
    if hr_zones:
        zones += [
            ActivityZoneTime(
                activity_id=activity_id,
                kind="hr",
                zone=zone["zoneNumber"],
                seconds=zone.get("secsInZone") or 0.0,
                low_boundary=zone.get("zoneLowBoundary"),
            )
            for zone in hr_zones
        ]
    else:
        zones += zones_from_summary_fields(activity_id, summary, "hr", "hrTimeInZone_")
    zones += zones_from_summary_fields(activity_id, summary, "power", "powerTimeInZone_")
    return zones


def zones_from_summary_fields(
    activity_id: int, summary: dict[str, Any], kind: str, prefix: str
) -> list[ActivityZoneTime]:
    return [
        ActivityZoneTime(
            activity_id=activity_id,
            kind=kind,
            zone=zone,
            seconds=summary[f"{prefix}{zone}"],
            low_boundary=None,
        )
        for zone in range(1, ZONE_COUNT + 1)
        if summary.get(f"{prefix}{zone}") is not None
    ]


def most_likely_exercise(exercise_set: dict[str, Any]) -> dict[str, Any]:
    candidates = exercise_set.get("exercises") or [{}]
    return max(candidates, key=lambda e: e.get("probability") or 0)


def set_indexes(exercise_sets: list[dict[str, Any]]) -> list[int]:
    """Garmin leaves messageIndex empty on sets added by editing an activity in Connect.
    Those get numbers after the highest real index, so edits keyed on real indexes stay put."""
    known = [s["messageIndex"] for s in exercise_sets if s.get("messageIndex") is not None]
    next_free = max(known, default=-1) + 1
    indexes = []
    for exercise_set in exercise_sets:
        index = exercise_set.get("messageIndex")
        if index is None:
            index = next_free
            next_free += 1
        indexes.append(index)
    return indexes


def sets_from_exercise_sets(activity_id: int, data: dict[str, Any]) -> list[StrengthSet]:
    exercise_sets = data.get("exerciseSets") or []
    sets = []
    for index, exercise_set in zip(set_indexes(exercise_sets), exercise_sets, strict=True):
        exercise = most_likely_exercise(exercise_set)
        weight_grams = exercise_set.get("weight")
        sets.append(
            StrengthSet(
                activity_id=activity_id,
                set_index=index,
                set_type=exercise_set.get("setType", "UNKNOWN"),
                exercise_category=exercise.get("category"),
                exercise_name=exercise.get("name"),
                reps=exercise_set.get("repetitionCount"),
                weight_kg=None if weight_grams is None else weight_grams / GRAMS_PER_KG,
                duration_s=exercise_set.get("duration"),
                start_time_gmt=parse_time(exercise_set.get("startTime")),
            )
        )
    return sets


def normalize_activity(session: Session, activity_id: int) -> Activity | None:
    summary = raw_store.get_activity(session, activity_id, "summary")
    if summary is None:
        return None

    activity = activity_from_summary(summary)
    existing = session.get(Activity, activity_id)
    if existing is not None:
        activity.is_commute = existing.is_commute
        activity.commute_override = existing.commute_override
    activity = session.merge(activity)

    for child in (ActivityLap, ActivityZoneTime, StrengthSet, ActivityHeartRate, Climb):
        session.execute(delete(child).where(child.activity_id == activity_id))

    splits = raw_store.get_activity(session, activity_id, "splits")
    if splits:
        session.add_all(laps_from_splits(activity_id, splits))

    hr_zones = raw_store.get_activity(session, activity_id, "hr_zones")
    session.add_all(zones_from_summary(activity_id, summary, hr_zones))

    details = raw_store.get_activity(session, activity_id, "details")
    heart_rate = samples(details)
    session.add_all(
        ActivityHeartRate(activity_id=activity_id, bpm=bpm, seconds=seconds)
        for bpm, seconds in histogram(heart_rate).items()
    )
    steady = drift(heart_rate)
    if steady is not None:
        activity.drift_first_hr = steady.first_half_hr
        activity.drift_second_hr = steady.second_half_hr
        activity.hr_drift_pct = steady.drift_pct
        activity.decoupling_pct = steady.decoupling_pct
    store_climbs(session, activity, details, sport_groups(session))

    exercise_sets = raw_store.get_activity(session, activity_id, "exercise_sets")
    if exercise_sets:
        session.add_all(sets_from_exercise_sets(activity_id, exercise_sets))

    return activity
