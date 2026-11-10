import math
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from garmin_coach import raw_store
from garmin_coach.metrics.commute import tag_commutes
from garmin_coach.metrics.load import (
    activity_load,
    athlete_heart_rates,
    banister_trimp,
    garmin_load_per_trimp,
    load_series,
)
from garmin_coach.metrics.recovery import baseline_status
from garmin_coach.metrics.running import climb_per_km, run_weeks, terrain
from garmin_coach.metrics.strength import (
    EffectiveSet,
    best_one_rep_max,
    effective_sets,
    epley_one_rep_max,
    is_single_leg_or_eccentric,
    mark_warmups,
    sets_per_muscle,
)
from garmin_coach.metrics.summary import running_lines
from garmin_coach.models import Activity, AthleteProfile, StrengthSetOverride
from garmin_coach.normalize import rebuild_all
from tests.garmin_data import activity_summary, exercise_sets

MONDAY = date(2026, 10, 19)


def strength_set(
    category: str, name: str | None = None, reps: int = 5, weight_kg: float = 100.0
) -> EffectiveSet:
    return EffectiveSet(MONDAY, 1, 0, category, name, reps, weight_kg)


def test_banister_trimp_matches_formula() -> None:
    reserve = (150 - 50) / (190 - 50)
    expected = 60 * reserve * 0.64 * math.exp(1.92 * reserve)

    assert banister_trimp(3600, 150, 50, 190, 1.92) == pytest.approx(expected)
    assert banister_trimp(3600, None, 50, 190, 1.92) is None


def test_activity_load_prefers_garmin_load() -> None:
    with_garmin_load = Activity(training_load=80.0, duration_s=3600, avg_hr=150)
    without = Activity(training_load=None, duration_s=3600, avg_hr=150)

    assert activity_load(with_garmin_load, 50, 190, 1.92) == 80.0
    assert activity_load(without, 50, 190, 1.92) > 0


def test_profile_max_hr_wins_over_a_spike_in_the_data(session: Session) -> None:
    session.add(
        Activity(
            id=1,
            type_key="running",
            start_time_local=datetime(2026, 10, 19, 7),
            start_time_gmt=datetime(2026, 10, 19, 5),
            local_date=MONDAY,
            max_hr=231.0,
        )
    )
    session.flush()
    assert athlete_heart_rates(session, MONDAY) == (60.0, 231.0)

    session.add(AthleteProfile(id=1, max_hr=188))
    session.flush()
    assert athlete_heart_rates(session, MONDAY) == (60.0, 188.0)


def test_trimp_is_scaled_to_the_athletes_garmin_load() -> None:
    trimp = banister_trimp(3600, 150, 50, 190, 1.92)
    assert trimp is not None
    with_both = [Activity(training_load=2 * trimp, duration_s=3600, avg_hr=150) for _ in range(10)]
    ski_without_garmin_load = Activity(training_load=None, duration_s=3600, avg_hr=150)

    scale = garmin_load_per_trimp(with_both, 50, 190, 1.92)

    assert scale == pytest.approx(2.0)
    assert garmin_load_per_trimp(with_both[:9], 50, 190, 1.92) == 1.0
    assert activity_load(ski_without_garmin_load, 50, 190, 1.92, scale) == pytest.approx(2 * trimp)


def test_load_series_reacts_faster_in_the_acute_average() -> None:
    first = date(2026, 1, 1)
    loads = {first + timedelta(days=offset): 100.0 for offset in range(200)}
    spike_day = first + timedelta(days=200)
    loads[spike_day] = 600.0

    series = load_series(loads, first, spike_day)

    before = series[-2]
    assert before.acute == pytest.approx(100.0, rel=0.01)
    assert before.chronic == pytest.approx(100.0, rel=0.01)
    assert series[-1].acute - before.acute > series[-1].chronic - before.chronic


def test_terrain_from_climb_per_km() -> None:
    assert climb_per_km(519, 13_079) == pytest.approx(39.7, abs=0.1)
    assert climb_per_km(100, 0) is None
    assert [terrain(c) for c in (None, 5, 15, 40)] == ["unknown", "flat", "rolling", "mountain"]


def test_run_weeks_counts_runs_terrain_and_back_to_back_days(session: Session) -> None:
    summaries = [
        activity_summary(
            1, "2026-10-24 09:00:00", distance_m=20_000, duration_s=7200, elevation_gain_m=900
        ),
        activity_summary(
            2, "2026-10-25 09:00:00", type_key="hiking", duration_s=6000, elevation_gain_m=1200
        ),
        activity_summary(
            3, "2026-10-21 18:00:00", distance_m=10_000, duration_s=3000, elevation_gain_m=50
        ),
    ]
    for summary in summaries:
        raw_store.put_activity(session, summary["activityId"], "summary", summary)
    rebuild_all(session)

    week = run_weeks(session, MONDAY, MONDAY)[0]

    assert week.runs == 2
    assert week.distance_km == 30.0
    assert week.elevation_gain_m == 950
    assert week.longest_run_h == 2.0
    assert week.hours_by_terrain["mountain"] == 2.0
    assert week.hours_by_terrain["flat"] == pytest.approx(3000 / 3600)
    assert week.back_to_back_long_days == 1


def test_sets_per_muscle_counts_secondary_muscles_as_half() -> None:
    sets = [
        strength_set("SQUAT"),
        strength_set("SQUAT"),
        strength_set("DEADLIFT"),
        strength_set("WARM_UP", reps=10),
        strength_set("CARDIO", reps=10),
    ]

    totals = sets_per_muscle(sets)

    assert totals["quads"] == 2
    assert totals["glutes"] == 3
    assert totals["hamstrings"] == 2
    assert totals["lower_back"] == 0.5
    assert "cardio" not in totals


def test_light_ramp_up_sets_are_not_hard_sets() -> None:
    sets = [
        strength_set("SQUAT", "BACK_SQUAT", reps=8, weight_kg=20),
        strength_set("SQUAT", "BACK_SQUAT", reps=5, weight_kg=50),
        strength_set("SQUAT", "BACK_SQUAT", weight_kg=70),
        strength_set("SQUAT", "BACK_SQUAT", weight_kg=70),
        strength_set("SQUAT", "GOBLET_SQUAT", weight_kg=24),
    ]

    mark_warmups(sets)

    assert [s.warmup for s in sets] == [True, True, False, False, False]
    assert sets_per_muscle(sets)["quads"] == 3


def test_epley_one_rep_max() -> None:
    assert epley_one_rep_max(100, 1) == 100
    assert epley_one_rep_max(75, 6) == pytest.approx(90.0)
    assert epley_one_rep_max(50, 20) is None
    assert epley_one_rep_max(None, 5) is None


def test_best_one_rep_max_per_exercise() -> None:
    sets = [
        EffectiveSet(MONDAY, 1, 0, "SQUAT", "BACK_SQUAT", 6, 75.0),
        EffectiveSet(MONDAY + timedelta(days=3), 2, 0, "SQUAT", "BACK_SQUAT", 3, 80.0),
    ]

    day, estimate = best_one_rep_max(sets)["BACK_SQUAT"]

    assert day == MONDAY
    assert estimate == pytest.approx(90.0)


def test_single_leg_and_eccentric_detection() -> None:
    assert is_single_leg_or_eccentric(strength_set("SQUAT", "BULGARIAN_SPLIT_SQUAT"))
    assert is_single_leg_or_eccentric(strength_set("LEG_CURL", "NORDIC_HAMSTRING_CURL"))
    assert is_single_leg_or_eccentric(strength_set("LUNGE", "LUNGE"))
    assert not is_single_leg_or_eccentric(strength_set("SQUAT", "BACK_SQUAT"))


def test_effective_sets_apply_overrides(session: Session) -> None:
    summary = activity_summary(1, "2026-10-20 18:00:00", type_key="strength_training")
    raw_store.put_activity(session, 1, "summary", summary)
    raw_store.put_activity(session, 1, "exercise_sets", exercise_sets())
    rebuild_all(session)
    session.add(
        StrengthSetOverride(
            activity_id=1,
            set_index=1,
            exercise_category="SQUAT",
            exercise_name="FRONT_SQUAT",
            reps=5,
            weight_kg=70.0,
            deleted=False,
            updated_at=datetime(2026, 10, 21),
        )
    )
    session.add(
        StrengthSetOverride(activity_id=1, set_index=0, deleted=True, updated_at=datetime.now())
    )
    session.flush()

    sets = effective_sets(session, MONDAY, MONDAY + timedelta(days=6))

    assert [(s.name, s.reps, s.weight_kg) for s in sets] == [("FRONT_SQUAT", 5, 70.0)]


def test_baseline_status_within_and_below() -> None:
    last = date(2026, 10, 28)
    values = {last - timedelta(days=offset): 4.2 + (offset % 2) * 0.1 for offset in range(60)}

    status = baseline_status(values, last)
    assert status is not None
    assert status.status == "within"

    for offset in range(7):
        values[last - timedelta(days=offset)] = 3.8
    status = baseline_status(values, last)
    assert status is not None
    assert status.status == "below"

    assert baseline_status({last: 4.0}, last) is None


def ride(activity_id: int, start: tuple[float, float], end: tuple[float, float]) -> dict[str, Any]:
    summary = activity_summary(
        activity_id, f"2026-10-{activity_id + 1:02d} 07:00:00", type_key="cycling"
    )
    summary["startLatitude"], summary["startLongitude"] = start
    summary["endLatitude"], summary["endLongitude"] = end
    return summary


def test_commutes_are_rides_between_the_two_most_visited_places(session: Session) -> None:
    home, work, cabin = (59.30, 5.50), (59.35, 5.60), (60.0, 6.0)
    rides = [ride(i, home, work) if i % 2 else ride(i, work, home) for i in range(1, 9)]
    rides.append(ride(9, home, cabin))
    for summary in rides:
        raw_store.put_activity(session, summary["activityId"], "summary", summary)
    rebuild_all(session)

    commutes = {a.id for a in session.query(Activity).filter(Activity.is_commute)}
    assert commutes == set(range(1, 9))

    session.get_one(Activity, 1).commute_override = False
    tag_commutes(session)
    assert session.get_one(Activity, 1).is_commute is False


def test_run_weeks_flag_a_jump_in_descent(session: Session) -> None:
    summaries = [
        activity_summary(1, "2026-09-23 09:00:00", elevation_gain_m=400),
        activity_summary(2, "2026-10-07 09:00:00", type_key="hiking", elevation_gain_m=1200),
        activity_summary(3, "2026-10-20 09:00:00", elevation_gain_m=300),
        activity_summary(4, "2026-10-24 09:00:00", type_key="hiking", elevation_gain_m=1500),
    ]
    for summary in summaries:
        raw_store.put_activity(session, summary["activityId"], "summary", summary)
    rebuild_all(session)

    week = run_weeks(session, MONDAY, MONDAY)[0]

    assert week.descent_on_foot_m == 1800
    assert week.biggest_descent_m == 1500
    assert week.descent_baseline_m == 400
    assert week.descent_ratio == 4.5
    assert week.descent_jump
    assert "a big jump in downhill load" in "\n".join(running_lines(session, MONDAY, MONDAY))
