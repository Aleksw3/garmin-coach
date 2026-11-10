import itertools
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.metrics.hills import distance_m
from garmin_coach.models import Goal, GoalCourse
from garmin_coach.normalize.climbs import STEP_M, Point, climb_ranges, even_profile

MAX_GPX_BYTES = 30_000_000
STORED_STEP_M = 100.0
STORED_EVERY = int(STORED_STEP_M / STEP_M)
MIN_COURSE_M = 500.0
WAYPOINT_REACH_M = 300.0
LEG_WITHOUT_WAYPOINTS_M = 10_000.0
MIN_LEG_M = 200.0
MAJOR_CLIMB_M = 100.0
MAJOR_CLIMB_MAX_DIP_M = 30.0


class CourseError(ValueError):
    pass


@dataclass(frozen=True)
class Waypoint:
    name: str
    distance_m: float


@dataclass(frozen=True)
class ParsedCourse:
    name: str | None
    profile: list[list[float]]
    waypoints: list[Waypoint]


@dataclass(frozen=True)
class Leg:
    name: str
    start_m: float
    end_m: float
    gain_m: float
    loss_m: float


@dataclass(frozen=True)
class Slope:
    start_m: float
    end_m: float
    change_m: float

    @property
    def grade(self) -> float:
        return self.change_m / (self.end_m - self.start_m)


@dataclass(frozen=True)
class Course:
    name: str | None
    profile: list[list[float]]
    waypoints: list[Waypoint]
    distance_m: float
    gain_m: float
    loss_m: float
    legs: list[Leg]
    climbs: list[Slope]
    descents: list[Slope]


def local_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if local_name(child) == name and child.text:
            return child.text.strip()
    return None


def position(element: ElementTree.Element) -> tuple[float, float]:
    try:
        return float(element.attrib["lat"]), float(element.attrib["lon"])
    except (KeyError, ValueError) as error:
        raise CourseError("A point in the GPX file has no position") from error


def track_points(root: ElementTree.Element) -> list[Point]:
    elements = [e for e in root.iter() if local_name(e) == "trkpt"] or [
        e for e in root.iter() if local_name(e) == "rtept"
    ]
    points: list[Point] = []
    distance = 0.0
    for element in elements:
        elevation = child_text(element, "ele")
        if elevation is None:
            continue
        lat, lon = position(element)
        if points:
            step = distance_m((points[-1].lat, points[-1].lon), (lat, lon))
            if step == 0:
                continue
            distance += step
        points.append(Point(distance, float(elevation), lat, lon, 0.0))
    return points


def waypoints_on_track(root: ElementTree.Element, points: list[Point]) -> list[Waypoint]:
    found = []
    for element in root.iter():
        if local_name(element) != "wpt":
            continue
        place = position(element)
        nearest = min(points, key=lambda p: distance_m(place, (p.lat, p.lon)))
        if distance_m(place, (nearest.lat, nearest.lon)) <= WAYPOINT_REACH_M:
            name = child_text(element, "name") or f"km {nearest.distance / 1000:.1f}"
            found.append(Waypoint(name[:100], round(nearest.distance)))
    return sorted(found, key=lambda w: w.distance_m)


def parse_gpx(content: bytes) -> ParsedCourse:
    if len(content) > MAX_GPX_BYTES:
        raise CourseError("The GPX file is too large")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise CourseError("The file is not a GPX file") from error
    points = track_points(root)
    if len(points) < 2 or points[-1].distance < MIN_COURSE_M:
        raise CourseError("The GPX file has no track with elevation")
    even = even_profile(points)
    stored = even[::STORED_EVERY]
    if stored[-1] is not even[-1]:
        stored.append(even[-1])
    name = next(
        (
            text
            for element in root.iter()
            if local_name(element) in ("trk", "rte", "metadata")
            and (text := child_text(element, "name"))
        ),
        None,
    )
    return ParsedCourse(
        name[:200] if name else None,
        [[round(p.distance), round(p.elevation, 1)] for p in stored],
        waypoints_on_track(root, points),
    )


def climbing(profile: list[list[float]]) -> tuple[float, float]:
    steps = [after[1] - before[1] for before, after in itertools.pairwise(profile)]
    return sum(s for s in steps if s > 0), -sum(s for s in steps if s < 0)


def part(profile: list[list[float]], start_m: float, end_m: float) -> list[list[float]]:
    return [point for point in profile if start_m <= point[0] <= end_m]


def legs(profile: list[list[float]], waypoints: list[Waypoint]) -> list[Leg]:
    finish = profile[-1][0]
    if waypoints:
        stops = [(w.name, w.distance_m) for w in waypoints]
    else:
        count = int(finish // LEG_WITHOUT_WAYPOINTS_M)
        stops = [
            (f"km {n * LEG_WITHOUT_WAYPOINTS_M / 1000:.0f}", n * LEG_WITHOUT_WAYPOINTS_M)
            for n in range(1, count + 1)
        ]
    stops = [(name, at) for name, at in stops if MIN_LEG_M <= at <= finish - MIN_LEG_M]
    found = []
    start = 0.0
    for name, end in [*stops, ("Finish", finish)]:
        if end - start < MIN_LEG_M:
            continue
        gain, loss = climbing(part(profile, start, end))
        found.append(Leg(name, start, end, gain, loss))
        start = end
    return found


def major_slopes(profile: list[list[float]], direction: int) -> list[Slope]:
    points = [Point(d, direction * e, 0.0, 0.0, 0.0) for d, e in profile]
    return [
        Slope(
            points[bottom].distance,
            points[top].distance,
            direction * (points[top].elevation - points[bottom].elevation),
        )
        for bottom, top in climb_ranges(
            points, max_dip_m=MAJOR_CLIMB_MAX_DIP_M, min_gain_m=MAJOR_CLIMB_M
        )
    ]


def describe(row: GoalCourse) -> Course:
    profile = [[float(d), float(e)] for d, e in row.profile]
    waypoints = [Waypoint(w["name"], float(w["distance_m"])) for w in row.waypoints]
    gain, loss = climbing(profile)
    return Course(
        name=row.name,
        profile=profile,
        waypoints=waypoints,
        distance_m=profile[-1][0],
        gain_m=gain,
        loss_m=loss,
        legs=legs(profile, waypoints),
        climbs=major_slopes(profile, 1),
        descents=major_slopes(profile, -1),
    )


def save_course(session: Session, goal: Goal, content: bytes) -> GoalCourse:
    parsed = parse_gpx(content)
    row = session.get(GoalCourse, goal.id) or GoalCourse(goal_id=goal.id)
    row.name = parsed.name
    row.uploaded_at = datetime.now()
    row.profile = parsed.profile
    row.waypoints = [{"name": w.name, "distance_m": w.distance_m} for w in parsed.waypoints]
    session.add(row)
    return row


def goal_course(session: Session, goal_id: int | None = None) -> tuple[Goal, GoalCourse] | None:
    query = select(Goal, GoalCourse).join(GoalCourse, GoalCourse.goal_id == Goal.id)
    if goal_id is not None:
        query = query.where(Goal.id == goal_id)
    else:
        query = query.where(Goal.status == "active").order_by(Goal.priority, Goal.target_date)
    found = session.execute(query).first()
    return (found[0], found[1]) if found else None


def course_text(course: Course) -> list[str]:
    def km(meters: float) -> str:
        return f"{meters / 1000:.1f}"

    def slope_line(slope: Slope) -> str:
        return (
            f"km {km(slope.start_m)} to {km(slope.end_m)}, {abs(slope.change_m):.0f} m "
            f"at {abs(100 * slope.grade):.0f}%"
        )

    lines = [
        f"Course{f' {course.name}' if course.name else ''}: {km(course.distance_m)} km, "
        f"{course.gain_m:.0f} m up, {course.loss_m:.0f} m down, from the uploaded GPX track",
        "Legs" + (" between the waypoints in the file:" if course.waypoints else ":"),
    ]
    lines += [
        f"- to {leg.name} at km {km(leg.end_m)}: {km(leg.end_m - leg.start_m)} km, "
        f"{leg.gain_m:.0f} m up, {leg.loss_m:.0f} m down"
        for leg in course.legs
    ]
    for title, slopes in (("climbs", course.climbs), ("descents", course.descents)):
        if slopes:
            lines.append(f"Long {title} of {MAJOR_CLIMB_M:.0f} m or more:")
            lines += [f"- {slope_line(slope)}" for slope in slopes]
    return lines


def as_json(course: Course) -> dict[str, Any]:
    return {
        "name": course.name,
        "distance_km": course.distance_m / 1000,
        "gain_m": course.gain_m,
        "loss_m": course.loss_m,
        "profile": [[d / 1000, e] for d, e in course.profile],
        "waypoints": [{"name": w.name, "km": w.distance_m / 1000} for w in course.waypoints],
        "legs": [
            {
                "name": leg.name,
                "start_km": leg.start_m / 1000,
                "end_km": leg.end_m / 1000,
                "gain_m": leg.gain_m,
                "loss_m": leg.loss_m,
            }
            for leg in course.legs
        ],
        "climbs": [slope_json(s) for s in course.climbs],
        "descents": [slope_json(s) for s in course.descents],
    }


def slope_json(slope: Slope) -> dict[str, float]:
    return {
        "start_km": slope.start_m / 1000,
        "end_km": slope.end_m / 1000,
        "change_m": slope.change_m,
        "grade": slope.grade,
    }
