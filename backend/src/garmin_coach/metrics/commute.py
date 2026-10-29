import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity

COMMUTE_TYPE_KEYS = ("cycling", "road_biking", "gravel_cycling", "e_bike_fitness")
SAME_PLACE_METERS = 400.0
MIN_VISITS_PER_PLACE = 4
EARTH_RADIUS_M = 6_371_000.0


@dataclass
class Place:
    lat: float
    lon: float
    visits: int = 0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def nearest_place(places: list[Place], lat: float, lon: float) -> int | None:
    for index, place in enumerate(places):
        if distance_m(place.lat, place.lon, lat, lon) <= SAME_PLACE_METERS:
            return index
    return None


def frequent_places(points: list[tuple[float, float]]) -> list[Place]:
    places: list[Place] = []
    for lat, lon in points:
        index = nearest_place(places, lat, lon)
        if index is None:
            places.append(Place(lat, lon, 1))
        else:
            places[index].visits += 1
    return sorted(places, key=lambda p: p.visits, reverse=True)


def ride_endpoints(activity: Activity) -> tuple[float, float, float, float] | None:
    start_lat, start_lon = activity.start_lat, activity.start_lon
    end_lat, end_lon = activity.end_lat, activity.end_lon
    if start_lat is None or start_lon is None or end_lat is None or end_lon is None:
        return None
    return start_lat, start_lon, end_lat, end_lon


def commute_places(rides: list[Activity]) -> tuple[Place, Place] | None:
    points = []
    for ride in rides:
        endpoints = ride_endpoints(ride)
        if endpoints is not None:
            points += [endpoints[:2], endpoints[2:]]
    places = [p for p in frequent_places(points) if p.visits >= MIN_VISITS_PER_PLACE]
    if len(places) < 2:
        return None
    return places[0], places[1]


def is_between(ride: Activity, home: Place, work: Place) -> bool:
    endpoints = ride_endpoints(ride)
    if endpoints is None:
        return False
    start = nearest_place([home, work], *endpoints[:2])
    end = nearest_place([home, work], *endpoints[2:])
    return start is not None and end is not None and start != end


def tag_commutes(session: Session) -> int:
    rides = list(session.scalars(select(Activity).where(Activity.type_key.in_(COMMUTE_TYPE_KEYS))))
    places = commute_places(rides)
    tagged = 0
    for ride in rides:
        detected = places is not None and is_between(ride, *places)
        ride.is_commute = detected if ride.commute_override is None else ride.commute_override
        if ride.is_commute:
            tagged += 1
    return tagged
