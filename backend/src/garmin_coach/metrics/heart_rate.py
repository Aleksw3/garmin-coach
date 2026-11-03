from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

MAX_SAMPLE_GAP_S = 30.0
DRIFT_WARMUP_S = 15 * 60.0
DRIFT_MIN_TEST_S = 30 * 60.0


@dataclass(frozen=True)
class Sample:
    seconds: float
    hr: float
    speed: float | None


@dataclass(frozen=True)
class Drift:
    first_half_hr: float
    second_half_hr: float
    drift_pct: float
    decoupling_pct: float | None


def samples(details: dict[str, Any] | None) -> list[Sample]:
    if not details:
        return []
    index = {d["key"]: d["metricsIndex"] for d in details.get("metricDescriptors") or []}
    hr_at = index.get("directHeartRate")
    time_at = index.get("sumDuration")
    if hr_at is None or time_at is None:
        return []
    speed_at = index.get("directSpeed")
    rows = [row["metrics"] for row in details.get("activityDetailMetrics") or []]
    result = []
    for current, following in pairwise(rows):
        hr, start, end = current[hr_at], current[time_at], following[time_at]
        if not hr or start is None or end is None:
            continue
        seconds = min(max(end - start, 0.0), MAX_SAMPLE_GAP_S)
        speed = current[speed_at] if speed_at is not None else None
        result.append(Sample(seconds, hr, speed))
    return result


def histogram(rows: list[Sample]) -> dict[int, float]:
    seconds: defaultdict[int, float] = defaultdict(float)
    for sample in rows:
        seconds[round(sample.hr)] += sample.seconds
    return {bpm: total for bpm, total in seconds.items() if total > 0}


def weighted_mean(values: list[tuple[float, float]]) -> float:
    weight = sum(seconds for _, seconds in values)
    return sum(value * seconds for value, seconds in values) / weight


def drift(rows: list[Sample]) -> Drift | None:
    elapsed = 0.0
    test: list[tuple[float, Sample]] = []
    for sample in rows:
        if elapsed >= DRIFT_WARMUP_S:
            test.append((elapsed - DRIFT_WARMUP_S, sample))
        elapsed += sample.seconds
    length = elapsed - DRIFT_WARMUP_S
    if length < DRIFT_MIN_TEST_S:
        return None
    halves = ([s for t, s in test if t < length / 2], [s for t, s in test if t >= length / 2])
    first_hr, second_hr = (weighted_mean([(s.hr, s.seconds) for s in half]) for half in halves)
    decoupling = None
    if all(s.speed is not None for s in rows):
        efficiency = [
            weighted_mean([(s.speed or 0.0, s.seconds) for s in half]) / hr
            for half, hr in zip(halves, (first_hr, second_hr), strict=True)
        ]
        if efficiency[0] > 0:
            decoupling = 100 * (efficiency[0] - efficiency[1]) / efficiency[0]
    return Drift(first_hr, second_hr, 100 * (second_hr - first_hr) / first_hr, decoupling)
