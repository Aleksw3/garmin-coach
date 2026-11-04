import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity, Climb
from garmin_coach.normalize.climbs import STEP_M, Point, scan_missing_climbs
from garmin_coach.normalize.sports import sport_groups

EFFORT_WINDOW_DAYS = 365
MIN_EFFORT_S = 60.0
MAX_EFFORT_S = 600.0
MIN_EFFORTS = 10
DEFAULT_FLAT_SPEED_MPS = 3.3
SHORT_HILL_SHARE = 0.85
ON_ROAD_M = 30.0
SAME_ROAD_SHARE = 0.5
HOME_WINDOW_DAYS = 180
HOME_REACH_M = 150.0
STEEPEST_STRETCH_M = 100.0
PITCH_STEPS = max(1, int(STEEPEST_STRETCH_M / STEP_M))
MAX_PITCH_ABOVE = 0.06
METERS_PER_DEGREE = 111_195.0
EARTH_RADIUS_M = 6_371_000.0


def cost_of_running(grade: float) -> float:
    # Minetti et al. 2002, energy per kg per meter at a gradient
    i = min(max(grade, -0.45), 0.45)
    return 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6


def uphill_speed(flat_speed: float, grade: float) -> float:
    return flat_speed * cost_of_running(0) / cost_of_running(grade)


@dataclass(frozen=True)
class Effort:
    flat_speed_mps: float
    from_data: bool


def hard_effort(session: Session, today: date) -> Effort:
    groups = sport_groups(session)
    rows = session.execute(
        select(Climb.length_m, Climb.gain_m, Climb.seconds, Activity.type_key)
        .join(Activity)
        .where(
            Activity.local_date >= today - timedelta(days=EFFORT_WINDOW_DAYS),
            Climb.seconds.between(MIN_EFFORT_S, MAX_EFFORT_S),
        )
    )
    speeds = [
        length / seconds * cost_of_running(gain / length) / cost_of_running(0)
        for length, gain, seconds, type_key in rows
        if groups.get(type_key) == "run"
    ]
    if len(speeds) < MIN_EFFORTS:
        return Effort(DEFAULT_FLAT_SPEED_MPS, False)
    return Effort(statistics.quantiles(speeds, n=20)[-1], True)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def home_point(
    session: Session, today: date, near: str | None = None
) -> tuple[float, float] | None:
    query = select(Activity.start_lat, Activity.start_lon, Activity.local_date).where(
        Activity.start_lat.is_not(None), Activity.start_lon.is_not(None)
    )
    if near:
        query = query.where(Activity.location_name.icontains(near))
    rows = [
        ((lat, lon), day)
        for lat, lon, day in session.execute(query)
        if lat is not None and lon is not None
    ]
    recent_since = today - timedelta(days=HOME_WINDOW_DAYS)
    starts = [start for start, day in rows if day >= recent_since] or [start for start, _ in rows]
    if not starts:
        return None
    return max(starts, key=lambda s: sum(distance_m(s, other) < HOME_REACH_M for other in starts))


@dataclass(frozen=True)
class Target:
    low_grade: float
    high_grade: float
    rep_seconds: float | None
    rep_meters: float | None
    flat_speed: float

    @property
    def grade(self) -> float:
        return (self.low_grade + self.high_grade) / 2

    def rep_time(self, a: Point, b: Point) -> float:
        length = b.distance - a.distance
        return length / uphill_speed(self.flat_speed, (b.elevation - a.elevation) / length)

    def share(self, a: Point, b: Point) -> float:
        if self.rep_meters is not None:
            return (b.distance - a.distance) / self.rep_meters
        assert self.rep_seconds is not None
        return self.rep_time(a, b) / self.rep_seconds


def pitches(points: list[Point]) -> list[float]:
    return [
        (points[i + PITCH_STEPS].elevation - points[i].elevation)
        / (points[i + PITCH_STEPS].distance - points[i].distance)
        for i in range(len(points) - PITCH_STEPS)
    ]


def steepest(pitch: list[float], start: int, end: int, grade: float) -> float:
    return max(pitch[start : end - PITCH_STEPS + 1], default=grade)


def best_section(points: list[Point], target: Target) -> tuple[int, int] | None:
    pitch = pitches(points)
    best: tuple[float, int, int] | None = None
    end = 1
    for start in range(len(points) - 1):
        end = max(end, start + 1)
        while end < len(points) - 1 and target.share(points[start], points[end]) < 1:
            end += 1
        if target.share(points[start], points[end]) < SHORT_HILL_SHARE:
            break
        a, b = points[start], points[end]
        grade = (b.elevation - a.elevation) / (b.distance - a.distance)
        if not target.low_grade <= grade <= target.high_grade:
            continue
        unevenness = steepest(pitch, start, end, grade) - grade
        if target.high_grade + MAX_PITCH_ABOVE < grade + unevenness:
            continue
        miss = abs(grade - target.grade) + unevenness / 2
        if best is None or miss < best[0]:
            best = (miss, start, end)
    return None if best is None else (best[1], best[2])


@dataclass
class Hill:
    start: tuple[float, float]
    end: tuple[float, float]
    length_m: float
    gain_m: float
    steepest_grade: float
    rep_seconds: float
    away_m: float
    visits: int
    last_day: date
    path_m: list[tuple[float, float]] = field(default_factory=list)

    @property
    def grade(self) -> float:
        return self.gain_m / self.length_m

    def map_url(self) -> str:
        return (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={self.start[0]:.6f},{self.start[1]:.6f}"
            f"&destination={self.end[0]:.6f},{self.end[1]:.6f}&travelmode=walking"
        )


@dataclass(frozen=True)
class HillSearch:
    center: tuple[float, float] | None
    effort: Effort
    hills: list[Hill]


def section_hill(
    activity: Activity, points: list[Point], target: Target, center: tuple[float, float]
) -> Hill:
    a, b = points[0], points[-1]
    grade = (b.elevation - a.elevation) / (b.distance - a.distance)
    east_scale = METERS_PER_DEGREE * math.cos(math.radians(center[0]))
    return Hill(
        start=(a.lat, a.lon),
        end=(b.lat, b.lon),
        length_m=b.distance - a.distance,
        gain_m=b.elevation - a.elevation,
        steepest_grade=steepest(pitches(points), 0, len(points) - 1, grade),
        rep_seconds=target.rep_time(a, b),
        away_m=distance_m(center, (a.lat, a.lon)),
        visits=1,
        last_day=activity.local_date,
        path_m=[(p.lat * METERS_PER_DEGREE, p.lon * east_scale) for p in points],
    )


def share_on(path: list[tuple[float, float]], other: list[tuple[float, float]]) -> float:
    reach = ON_ROAD_M**2
    on_road = sum(any((x - u) ** 2 + (y - v) ** 2 < reach for u, v in other) for x, y in path)
    return on_road / len(path)


def apart(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    return any(
        min(p[axis] for p in a) > max(p[axis] for p in b) + ON_ROAD_M
        or min(p[axis] for p in b) > max(p[axis] for p in a) + ON_ROAD_M
        for axis in (0, 1)
    )


def same_road(a: Hill, b: Hill) -> bool:
    if apart(a.path_m, b.path_m):
        return False
    return max(share_on(a.path_m, b.path_m), share_on(b.path_m, a.path_m)) >= SAME_ROAD_SHARE


def merged(hills: list[Hill], grade: float) -> list[Hill]:
    groups: list[Hill] = []
    for hill in hills:
        index = next((i for i, g in enumerate(groups) if same_road(g, hill)), None)
        if index is None:
            groups.append(hill)
            continue
        group = groups[index]
        visits = group.visits + 1
        last_day = max(group.last_day, hill.last_day)
        if abs(hill.grade - grade) < abs(group.grade - grade):
            groups[index] = group = hill
        group.visits = visits
        group.last_day = last_day
    return groups


def find_hills(
    session: Session,
    today: date,
    grade_pct: float,
    tolerance_pct: float,
    rep_minutes: float | None = None,
    rep_meters: float | None = None,
    near: str | None = None,
    max_km: float = 10.0,
    limit: int = 5,
) -> HillSearch:
    if scan_missing_climbs(session):
        session.commit()
    effort = hard_effort(session, today)
    center = home_point(session, today, near)
    if center is None:
        return HillSearch(None, effort, [])
    target = Target(
        low_grade=(grade_pct - tolerance_pct) / 100,
        high_grade=(grade_pct + tolerance_pct) / 100,
        rep_seconds=None if rep_minutes is None else rep_minutes * 60,
        rep_meters=rep_meters,
        flat_speed=effort.flat_speed_mps,
    )
    sections = []
    for climb, activity in session.execute(select(Climb, Activity).join(Activity)):
        if distance_m(center, (climb.start_lat, climb.start_lon)) > max_km * 1000:
            continue
        points = [Point(*values) for values in climb.track]
        section = best_section(points, target)
        if section is not None:
            first, last = section
            sections.append(section_hill(activity, points[first : last + 1], target, center))
    hills = sorted(merged(sections, target.grade), key=lambda h: h.away_m)
    return HillSearch(center, effort, hills[:limit])
