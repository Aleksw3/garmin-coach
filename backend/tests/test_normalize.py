from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach import raw_store
from garmin_coach.models import Activity, ActivityLap, ActivityZoneTime, StrengthSet
from garmin_coach.normalize import normalize_activity
from garmin_coach.normalize.activities import (
    activity_from_summary,
    laps_from_splits,
    sets_from_exercise_sets,
    zones_from_summary,
)
from garmin_coach.normalize.daily import (
    body_composition_entries,
    training_status_label,
    wellness_from_raw,
)
from tests.garmin_data import activity_summary, daily, exercise_sets, hr_zones, splits

DAY = date(2026, 10, 20)


def test_activity_summary_fields() -> None:
    activity = activity_from_summary(activity_summary(7, "2026-10-20 23:30:00"))

    assert activity.id == 7
    assert activity.type_key == "running"
    assert activity.start_time_local == datetime(2026, 10, 20, 23, 30)
    assert activity.local_date == DAY
    assert activity.elevation_gain_m == 300.0
    assert activity.training_load == 80.5
    assert activity.avg_grade_adjusted_speed_mps is not None


def test_laps_use_lap_index_and_grade_adjusted_speed() -> None:
    laps = laps_from_splits(7, splits())

    assert [lap.lap_index for lap in laps] == [1, 2]
    assert laps[0].elevation_gain_m == 200.0
    assert laps[0].avg_grade_adjusted_speed_mps == 3.1
    assert laps[0].start_time_gmt == datetime(2026, 10, 20, 8, 0)


def test_hr_zones_prefer_zone_endpoint_with_boundaries() -> None:
    zones = zones_from_summary(7, activity_summary(7, "2026-10-20 08:00:00"), hr_zones())

    hr = [z for z in zones if z.kind == "hr"]
    power = [z for z in zones if z.kind == "power"]
    assert [z.seconds for z in hr] == [100.0, 200.0, 300.0, 400.0, 500.0]
    assert hr[0].low_boundary == 115
    assert [z.seconds for z in power] == [1800.0, 1800.0]


def test_hr_zones_fall_back_to_summary_fields() -> None:
    zones = zones_from_summary(7, activity_summary(7, "2026-10-20 08:00:00"), None)

    hr = [z for z in zones if z.kind == "hr"]
    assert [z.seconds for z in hr] == [600.0, 2400.0, 600.0, 0.0, 0.0]
    assert all(z.low_boundary is None for z in hr)


def test_strength_sets_pick_likeliest_exercise_and_convert_grams() -> None:
    sets = sets_from_exercise_sets(7, exercise_sets())

    warm_up, squat, rest = sets
    assert warm_up.exercise_category == "WARM_UP"
    assert warm_up.reps is None
    assert warm_up.weight_kg is None
    assert squat.exercise_name == "BACK_SQUAT"
    assert squat.reps == 6
    assert squat.weight_kg == 75.0
    assert rest.set_type == "REST"


def test_sets_added_in_garmin_connect_get_free_indexes() -> None:
    data = exercise_sets()
    data["exerciseSets"].insert(
        1, {"exercises": [], "setType": "REST", "duration": 0.0, "messageIndex": None}
    )

    sets = sets_from_exercise_sets(7, data)

    assert [s.set_index for s in sets] == [0, 3, 1, 2]


def test_wellness_fields_from_all_daily_kinds() -> None:
    kinds = ("stats", "sleep", "hrv", "readiness", "training_status")
    wellness = wellness_from_raw(DAY, {kind: daily(kind, DAY) for kind in kinds})

    assert wellness.resting_hr == 43
    assert wellness.sleep_s == 28740
    assert wellness.sleep_score == 93
    assert wellness.hrv_last_night == 64
    assert (wellness.hrv_baseline_low, wellness.hrv_baseline_high) == (69, 79)
    assert wellness.readiness_score == 72
    assert wellness.acute_load == 261
    assert wellness.training_status == "Strained"
    assert wellness.vo2max == 55.3


def test_wellness_tolerates_missing_and_null_data() -> None:
    wellness = wellness_from_raw(DAY, {"hrv": None, "readiness": []})

    assert wellness.day == DAY
    assert wellness.hrv_last_night is None
    assert wellness.readiness_score is None


def test_training_status_label() -> None:
    assert training_status_label("PRODUCTIVE_3") == "Productive"
    assert training_status_label("NOT_ACTIVE_1") == "Not active"
    assert training_status_label(None) is None


def test_body_composition_converts_grams() -> None:
    entries = body_composition_entries(
        {"dateWeightList": [{"calendarDate": "2026-10-20", "weight": 72500.0, "bodyFat": 12.5}]}
    )

    assert entries[0].day == DAY
    assert entries[0].weight_kg == 72.5
    assert entries[0].body_fat_pct == 12.5


def test_normalize_activity_replaces_children_and_keeps_commute_override(
    session: Session,
) -> None:
    raw_store.put_activity(session, 7, "summary", activity_summary(7, "2026-10-20 08:00:00"))
    raw_store.put_activity(session, 7, "splits", splits())
    activity = normalize_activity(session, 7)
    assert activity is not None
    activity.commute_override = True
    session.commit()

    normalize_activity(session, 7)
    session.commit()

    activity = session.get_one(Activity, 7)
    assert activity.commute_override is True
    assert len(session.scalars(select(ActivityLap)).all()) == 2
    assert len(session.scalars(select(ActivityZoneTime)).all()) == 7
    assert session.scalars(select(StrengthSet)).all() == []
