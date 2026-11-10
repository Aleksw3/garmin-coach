from garmin_coach.models import ActivityFuel

LONG_ENOUGH_TO_FUEL_S = 90 * 60


def per_hour(amount: float | None, duration_s: float | None) -> float | None:
    if amount is None or not duration_s:
        return None
    return amount / (duration_s / 3600)


def fuel_text(fuel: ActivityFuel | None, duration_s: float | None) -> str | None:
    if fuel is None:
        return None
    parts = []
    for amount, unit in ((fuel.carbs_g, "g carbohydrate"), (fuel.fluid_ml, "ml fluid")):
        if amount is None:
            continue
        rate = per_hour(amount, duration_s)
        parts.append(f"{amount:.0f} {unit}" + (f" ({rate:.0f} per hour)" if rate else ""))
    if fuel.gut:
        parts.append(f"stomach: {fuel.gut}")
    if fuel.note:
        parts.append(f"note: {fuel.note}")
    return ", ".join(parts) or None
