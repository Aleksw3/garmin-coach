import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.course import Course, describe
from garmin_coach.models import Activity, Goal, GoalCourse
from garmin_coach.normalize.sports import sport_groups

REFERENCE_WINDOW_DAYS = 180
MIN_REFERENCE_S = 60 * 60
REFERENCES_USED = 3
CLIMB_M_PER_FLAT_KM = 100.0
RIEGEL_EXPONENT = 1.06
ULTRA_EXPONENT = 1.15
ON_FOOT_GROUPS = ("run", "vertical")


def effort_km(distance_km: float, gain_m: float) -> float:
    return distance_km + gain_m / CLIMB_M_PER_FLAT_KM


@dataclass(frozen=True)
class Reference:
    activity_id: int
    day: date
    name: str | None
    distance_km: float
    gain_m: float
    seconds: float

    @property
    def effort_km(self) -> float:
        return effort_km(self.distance_km, self.gain_m)

    def race_seconds(self, race_effort_km: float, exponent: float) -> float:
        return float(self.seconds * (race_effort_km / self.effort_km) ** exponent)


@dataclass(frozen=True)
class Arrival:
    name: str
    km: float
    fast_s: float
    slow_s: float


@dataclass(frozen=True)
class Projection:
    distance_km: float
    gain_m: float
    effort_km: float
    fast_s: float
    slow_s: float
    references: list[Reference]
    arrivals: list[Arrival]


def references(session: Session, today: date) -> list[Reference]:
    groups = sport_groups(session)
    activities = session.scalars(
        select(Activity).where(
            Activity.local_date > today - timedelta(days=REFERENCE_WINDOW_DAYS),
            Activity.local_date <= today,
            Activity.duration_s >= MIN_REFERENCE_S,
            Activity.distance_m > 0,
        )
    )
    return [
        Reference(
            a.id,
            a.local_date,
            a.name,
            (a.distance_m or 0) / 1000,
            a.elevation_gain_m or 0,
            a.duration_s or 0,
        )
        for a in activities
        if groups.get(a.type_key) in ON_FOOT_GROUPS
    ]


def arrivals(course: Course, race_effort_km: float, fast_s: float, slow_s: float) -> list[Arrival]:
    found = []
    done = 0.0
    for leg in course.legs:
        done += effort_km((leg.end_m - leg.start_m) / 1000, leg.gain_m)
        share = done / race_effort_km
        found.append(Arrival(leg.name, leg.end_m / 1000, share * fast_s, share * slow_s))
    return found


def project(session: Session, goal: Goal, today: date) -> Projection | None:
    row = session.get(GoalCourse, goal.id)
    course = describe(row) if row else None
    if course is not None:
        distance_km, gain_m = course.distance_m / 1000, course.gain_m
    elif goal.distance_km:
        distance_km, gain_m = goal.distance_km, goal.elevation_gain_m or 0
    else:
        return None
    race_effort_km = effort_km(distance_km, gain_m)
    used = sorted(
        references(session, today), key=lambda r: r.race_seconds(race_effort_km, RIEGEL_EXPONENT)
    )[:REFERENCES_USED]
    if not used:
        return None
    fast_s = statistics.median(r.race_seconds(race_effort_km, RIEGEL_EXPONENT) for r in used)
    slow_s = statistics.median(r.race_seconds(race_effort_km, ULTRA_EXPONENT) for r in used)
    if course is not None:
        legs_effort = sum(
            effort_km((leg.end_m - leg.start_m) / 1000, leg.gain_m) for leg in course.legs
        )
        leg_arrivals = arrivals(course, legs_effort, fast_s, slow_s)
    else:
        leg_arrivals = []
    return Projection(distance_km, gain_m, race_effort_km, fast_s, slow_s, used, leg_arrivals)


def clock(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min"


def projection_text(projection: Projection) -> list[str]:
    lines = [
        f"Finish estimate {clock(projection.fast_s)} to {clock(projection.slow_s)} for "
        f"{projection.distance_km:.1f} km with {projection.gain_m:.0f} m climbing "
        f"({projection.effort_km:.0f} effort-km, where 100 m climbing counts as 1 km).",
        "Method: the time of each long run or hike below, scaled with "
        f"(race effort-km / run effort-km)^{RIEGEL_EXPONENT:g} for the fast end and "
        f"^{ULTRA_EXPONENT:g} for the slow end, then the median. It is a rough estimate. "
        "It assumes even effort and does not know about technical ground, heat, night, aid "
        "station stops or how hard the runs below were. Say so when you use it.",
        f"Based on the {len(projection.references)} runs or hikes of 60 minutes or more from "
        f"the last {REFERENCE_WINDOW_DAYS} days that predict the fastest time:",
    ]
    lines += [
        f"- {r.day} activity {r.activity_id} {r.name or ''}: {r.distance_km:.1f} km, "
        f"{r.gain_m:.0f} m up in {clock(r.seconds)}"
        for r in projection.references
    ]
    if projection.arrivals:
        lines.append("Arrival at the end of each leg, in time from the start:")
        lines += [
            f"- {a.name} at km {a.km:.1f}: {clock(a.fast_s)} to {clock(a.slow_s)}"
            for a in projection.arrivals
        ]
    return lines
