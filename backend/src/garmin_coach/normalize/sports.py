from sqlalchemy import select
from sqlalchemy.orm import Session

from garmin_coach.models import Activity, SportMapping

DEFAULT_SPORT_GROUPS = {
    "running": "run",
    "trail_running": "run",
    "treadmill_running": "run",
    "track_running": "run",
    "ultra_run": "run",
    "hiking": "vertical",
    "stair_climbing": "vertical",
    "mountaineering": "vertical",
    "backcountry_skiing": "ski",
    "backcountry_skiing_snowboarding_ws": "ski",
    "skate_skiing_ws": "ski",
    "cross_country_skiing_ws": "ski",
    "cycling": "cycling",
    "road_biking": "cycling",
    "gravel_cycling": "cycling",
    "mountain_biking": "cycling",
    "indoor_cycling": "cycling",
    "elliptical": "other_endurance",
    "resort_skiing": "alpine",
    "resort_skiing_snowboarding_ws": "alpine",
    "strength_training": "strength",
    "bouldering": "other",
    "squash": "other",
    "paddelball": "other",
}

OTHER = "other"


def seed_sport_mapping(session: Session) -> None:
    existing = set(session.scalars(select(SportMapping.type_key)))
    for type_key, group in DEFAULT_SPORT_GROUPS.items():
        if type_key not in existing:
            session.add(SportMapping(type_key=type_key, sport_group=group))


def sport_groups(session: Session) -> dict[str, str]:
    return {m.type_key: m.sport_group for m in session.scalars(select(SportMapping))}


def unmapped_type_keys(session: Session) -> list[str]:
    mapped = select(SportMapping.type_key)
    query = select(Activity.type_key).distinct().where(Activity.type_key.not_in(mapped))
    return sorted(session.scalars(query))
