from garmin_coach.models import ActivityRating

LEGS = {1: "fresh", 2: "normal", 3: "heavy", 4: "sore", 5: "very sore"}


def rating_text(rating: ActivityRating | None) -> str | None:
    if rating is None:
        return None
    parts = []
    if rating.effort is not None:
        parts.append(f"effort {rating.effort}/10")
    if rating.legs is not None:
        parts.append(f"legs {rating.legs}/5 ({LEGS[rating.legs]})")
    if rating.pain:
        parts.append(f"pain: {rating.pain}")
    if rating.note:
        parts.append(f"note: {rating.note}")
    return ", ".join(parts) or None
