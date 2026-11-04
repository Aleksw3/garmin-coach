import statistics
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach import raw_store
from garmin_coach.models import Activity, Climb
from garmin_coach.normalize.sports import sport_groups

TRACK_FIELDS = (
    "sumDistance",
    "directElevation",
    "directLatitude",
    "directLongitude",
    "sumDuration",
)
CLIMB_GROUPS = ("run", "vertical", "cycling")
STEP_M = 20.0
SMOOTHING_REACH_M = 40.0
MAX_DIP_M = 4.0
MIN_GAIN_M = 15.0
MIN_GRADE = 0.03


@dataclass(frozen=True)
class Point:
    distance: float
    elevation: float
    lat: float
    lon: float
    seconds: float


def track_points(details: dict[str, Any] | None) -> list[Point]:
    if not details:
        return []
    index = {d["key"]: d["metricsIndex"] for d in details.get("metricDescriptors") or []}
    if any(key not in index for key in TRACK_FIELDS):
        return []
    columns = [index[key] for key in TRACK_FIELDS]
    points: list[Point] = []
    for row in details.get("activityDetailMetrics") or []:
        values = [row["metrics"][column] for column in columns]
        if any(value is None for value in values):
            continue
        point = Point(*values)
        if not points or point.distance > points[-1].distance:
            points.append(point)
    return points


def between(a: Point, b: Point, distance: float) -> Point:
    share = (distance - a.distance) / (b.distance - a.distance)

    def mix(start: float, end: float) -> float:
        return start + share * (end - start)

    return Point(
        distance,
        mix(a.elevation, b.elevation),
        mix(a.lat, b.lat),
        mix(a.lon, b.lon),
        mix(a.seconds, b.seconds),
    )


def even_profile(points: list[Point]) -> list[Point]:
    if len(points) < 2:
        return []
    even = []
    index = 0
    distance = points[0].distance
    while distance <= points[-1].distance:
        while points[index + 1].distance < distance:
            index += 1
        even.append(between(points[index], points[index + 1], distance))
        distance += STEP_M
    reach = int(SMOOTHING_REACH_M / STEP_M)
    elevations = [point.elevation for point in even]
    return [
        replace(point, elevation=statistics.fmean(elevations[max(0, i - reach) : i + reach + 1]))
        for i, point in enumerate(even)
    ]


def climb_ranges(profile: list[Point]) -> list[tuple[int, int]]:
    ranges = []
    start = 0
    while start < len(profile) - 1:
        top = start
        for index in range(start + 1, len(profile)):
            if profile[index].elevation > profile[top].elevation:
                top = index
            elif profile[top].elevation - profile[index].elevation > MAX_DIP_M:
                break
        bottom = min(range(top, start - 1, -1), key=lambda i: profile[i].elevation)
        gain = profile[top].elevation - profile[bottom].elevation
        length = profile[top].distance - profile[bottom].distance
        if gain >= MIN_GAIN_M and gain >= MIN_GRADE * length:
            ranges.append((bottom, top))
            start = top + 1
        else:
            start += 1
    return ranges


def find_climbs(activity_id: int, details: dict[str, Any] | None) -> list[Climb]:
    profile = even_profile(track_points(details))
    climbs = []
    for bottom, top in climb_ranges(profile):
        part = profile[bottom : top + 1]
        first, last = part[0], part[-1]
        climbs.append(
            Climb(
                activity_id=activity_id,
                start_lat=first.lat,
                start_lon=first.lon,
                length_m=last.distance - first.distance,
                gain_m=last.elevation - first.elevation,
                seconds=last.seconds - first.seconds,
                track=[
                    [
                        round(p.distance - first.distance),
                        round(p.elevation, 1),
                        round(p.lat, 6),
                        round(p.lon, 6),
                        round(p.seconds - first.seconds),
                    ]
                    for p in part
                ],
            )
        )
    return climbs


def store_climbs(
    session: Session, activity: Activity, details: dict[str, Any] | None, groups: dict[str, str]
) -> None:
    if groups.get(activity.type_key) in CLIMB_GROUPS:
        session.add_all(find_climbs(activity.id, details))
    activity.climbs_scanned = True


def scan_missing_climbs(session: Session) -> int:
    groups = sport_groups(session)
    activities = session.scalars(select(Activity).where(Activity.climbs_scanned.is_(False))).all()
    for activity in activities:
        details = (
            raw_store.get_activity(session, activity.id, "details")
            if groups.get(activity.type_key) in CLIMB_GROUPS
            else None
        )
        store_climbs(session, activity, details, groups)
    return len(activities)
