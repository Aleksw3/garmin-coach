#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["garminconnect==0.3.20"]
# ///
"""Phase 0 probe: check that Garmin login and data pulls work on this machine.

Saves every response as raw JSON under the output directory and prints a report.
See docs/PLAN.md, phase 0.
"""

import argparse
import getpass
import json
import os
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

ROOT = Path(__file__).resolve().parent.parent

SPORT_GROUPS = {
    "run": ("running",),
    "strength": ("strength",),
    "ski_touring": ("backcountry",),
    "cross_country_ski": ("cross_country", "skate_ski"),
    "alpine_ski": ("resort",),
    "cycling": ("cycling", "biking"),
}

DAILY_ENDPOINTS = {
    "stats": "get_stats",
    "sleep": "get_sleep_data",
    "hrv": "get_hrv_data",
    "readiness": "get_training_readiness",
    "training_status": "get_training_status",
}

ACTIVITY_ENDPOINTS = {
    "activity": "get_activity",
    "splits": "get_activity_splits",
    "hr_zones": "get_activity_hr_in_timezones",
    "details": "get_activity_details",
    "weather": "get_activity_weather",
}

ACTIVITY_CALL_NAMES = {*ACTIVITY_ENDPOINTS, "exercise_sets"}


@dataclass
class Call:
    name: str
    seconds: float
    bytes: int
    error: str | None


class Probe:
    def __init__(self, client: Garmin, out: Path, delay: float) -> None:
        self.client = client
        self.out = out
        self.delay = delay
        self.calls: list[Call] = []

    def fetch(self, name: str, path: str, fn: Callable[..., Any], *args: Any) -> Any:
        start = time.monotonic()
        data, error = None, None
        try:
            data = fn(*args)
        except GarminConnectTooManyRequestsError:
            raise
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
        size = 0
        if data is not None:
            text = json.dumps(data, indent=2, ensure_ascii=False)
            target = self.out / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            size = len(text.encode())
        self.calls.append(Call(name, time.monotonic() - start, size, error))
        time.sleep(self.delay)
        return data


def type_key(activity: dict[str, Any]) -> str:
    return (activity.get("activityType") or {}).get("typeKey", "unknown")


def sport_group(key: str) -> str | None:
    return next(
        (
            group
            for group, parts in SPORT_GROUPS.items()
            if any(p in key for p in parts)
        ),
        None,
    )


def login(token_dir: Path) -> tuple[Garmin, str]:
    token_dir.mkdir(parents=True, exist_ok=True)
    token_dir.chmod(0o700)
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")

    def prompt_mfa() -> str:
        return input("Garmin MFA code: ").strip()

    def credential_login() -> Garmin:
        client = Garmin(
            email or input("Garmin email: ").strip(),
            password or getpass.getpass("Garmin password: "),
            prompt_mfa=prompt_mfa,
        )
        client.login(str(token_dir))
        return client

    if not any(token_dir.iterdir()):
        return credential_login(), "credentials (no saved tokens)"
    try:
        client = Garmin(email, password, prompt_mfa=prompt_mfa)
        client.login(str(token_dir))
        return client, "saved tokens"
    except GarminConnectAuthenticationError as e:
        if email and password:
            raise
        print(f"Saved tokens failed ({e}), logging in with credentials")
        return credential_login(), "credentials (saved tokens rejected)"


def pick_samples(
    recent: list[dict[str, Any]], history: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    samples = {a["activityId"]: a for a in recent}
    covered = {sport_group(type_key(a)) for a in recent}
    for activity in history:
        group = sport_group(type_key(activity))
        if group and group not in covered:
            samples[activity["activityId"]] = activity
            covered.add(group)
    return list(samples.values())


def fetch_activity(probe: Probe, activity: dict[str, Any]) -> None:
    activity_id = activity["activityId"]
    for name, method in ACTIVITY_ENDPOINTS.items():
        probe.fetch(
            name,
            f"activities/{activity_id}/{name}.json",
            getattr(probe.client, method),
            activity_id,
        )
    if sport_group(type_key(activity)) == "strength":
        probe.fetch(
            "exercise_sets",
            f"activities/{activity_id}/exercise_sets.json",
            probe.client.get_activity_exercise_sets,
            activity_id,
        )


def has_strength_sets(out: Path, samples: list[dict[str, Any]]) -> bool:
    for activity in samples:
        path = out / f"activities/{activity['activityId']}/exercise_sets.json"
        if not path.exists():
            continue
        sets = json.loads(path.read_text()).get("exerciseSets") or []
        if any(s.get("setType") == "ACTIVE" and s.get("repetitionCount") for s in sets):
            return True
    return False


def has_daily_field(out: Path, kind: str, field: str) -> bool:
    documents = (
        json.loads(path.read_text()) for path in out.glob(f"daily/*/{kind}.json")
    )
    return any(isinstance(d, dict) and d.get(field) for d in documents)


def build_report(
    probe: Probe,
    login_method: str,
    days: int,
    history_days: int,
    recent: list[dict[str, Any]],
    history: list[dict[str, Any]],
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    type_counts = Counter(type_key(a) for a in history)
    groups_found = {group: 0 for group in SPORT_GROUPS}
    for key, count in type_counts.items():
        if group := sport_group(key):
            groups_found[group] += count

    run_with_elevation = any(
        sport_group(type_key(a)) == "run" and (a.get("elevationGain") or 0) > 0
        for a in samples
    )
    checks = {
        "strength activity with sets and reps": has_strength_sets(probe.out, samples),
        "run with elevation gain": run_with_elevation,
        "ski touring in history": groups_found["ski_touring"] > 0,
        "sleep data": has_daily_field(probe.out, "sleep", "dailySleepDTO"),
        "hrv data": has_daily_field(probe.out, "hrv", "hrvSummary"),
    }

    ok_calls = [c for c in probe.calls if c.error is None]
    seconds_per_call = statistics.mean(c.seconds for c in ok_calls) if ok_calls else 0
    activity_calls = [c for c in probe.calls if c.name in ACTIVITY_CALL_NAMES]
    sampled = max(len(samples), 1)
    calls_per_activity = len(activity_calls) / sampled
    bytes_per_activity = sum(c.bytes for c in activity_calls) / sampled
    activities_per_year = len(history) * 365 / history_days
    backfill_calls = 2 * (
        activities_per_year * calls_per_activity + 365 * len(DAILY_ENDPOINTS)
    )

    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "login_method": login_method,
        "days": days,
        "history_days": history_days,
        "recent_activities": len(recent),
        "history_activities": len(history),
        "activity_type_counts": dict(type_counts.most_common()),
        "sport_groups_in_history": groups_found,
        "unmatched_type_keys": sorted(k for k in type_counts if sport_group(k) is None),
        "sampled_activities": [
            {
                "id": a["activityId"],
                "type": type_key(a),
                "start": a.get("startTimeLocal"),
            }
            for a in samples
        ],
        "checks": checks,
        "calls": len(probe.calls),
        "failed_calls": [asdict(c) for c in probe.calls if c.error],
        "seconds_per_call": round(seconds_per_call, 2),
        "bytes_per_activity": round(bytes_per_activity),
        "estimated_24_month_backfill": {
            "calls": round(backfill_calls),
            "hours_at_2s_delay": round(
                backfill_calls * (seconds_per_call + 2) / 3600, 1
            ),
            "raw_megabytes": round(2 * activities_per_year * bytes_per_activity / 1e6),
        },
    }


def print_report(report: dict[str, Any], out: Path) -> None:
    print(f"\nLogin: {report['login_method']}")
    print(
        f"Activities: {report['recent_activities']} in the last {report['days']} days, "
        f"{report['history_activities']} in the last {report['history_days']} days"
    )
    print("\nActivity types in history:")
    for key, count in report["activity_type_counts"].items():
        print(f"  {count:5d}  {key}  ({sport_group(key) or 'no group'})")
    print("\nChecks:")
    for name, passed in report["checks"].items():
        print(f"  [{'x' if passed else ' '}] {name}")
    print(f"\nCalls: {report['calls']}, failed: {len(report['failed_calls'])}")
    for call in report["failed_calls"]:
        print(f"  {call['name']}: {call['error']}")
    backfill = report["estimated_24_month_backfill"]
    print(
        f"Seconds per call: {report['seconds_per_call']}. "
        f"Estimated 24-month backfill: {backfill['calls']} calls, "
        f"{backfill['hours_at_2s_delay']} h, {backfill['raw_megabytes']} MB raw JSON"
    )
    print(f"\nRaw data and report.json: {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="days of full data to pull")
    parser.add_argument(
        "--history-days",
        type=int,
        default=730,
        help="days of activity list to scan for one example of each sport",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="seconds between requests"
    )
    parser.add_argument("--tokens", type=Path, default=ROOT / "data/garmin_tokens")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out = args.out or ROOT / "data/probe" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    login_start = time.monotonic()
    try:
        client, login_method = login(args.tokens)
    except GarminConnectAuthenticationError as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 1
    print(f"Logged in with {login_method} in {time.monotonic() - login_start:.1f} s")

    probe = Probe(client, out, args.delay)
    today = date.today()
    recent_start = today - timedelta(days=args.days - 1)
    history_start = today - timedelta(days=args.history_days)

    try:
        probe.fetch("profile", "profile/user_profile.json", client.get_user_profile)
        recent = (
            probe.fetch(
                "activity_list",
                "activities/list_recent.json",
                client.get_activities_by_date,
                recent_start.isoformat(),
                today.isoformat(),
            )
            or []
        )
        history = (
            probe.fetch(
                "activity_list",
                "activities/list_history.json",
                client.get_activities_by_date,
                history_start.isoformat(),
                today.isoformat(),
            )
            or []
        )
        samples = pick_samples(recent, history)
        print(f"Fetching details for {len(samples)} activities")
        for activity in samples:
            fetch_activity(probe, activity)

        print(f"Fetching daily data for {args.days} days")
        for offset in range(args.days):
            day = (recent_start + timedelta(days=offset)).isoformat()
            for name, method in DAILY_ENDPOINTS.items():
                probe.fetch(
                    name, f"daily/{day}/{name}.json", getattr(client, method), day
                )
        probe.fetch(
            "body_composition",
            "body_composition.json",
            client.get_body_composition,
            recent_start.isoformat(),
            today.isoformat(),
        )
    except GarminConnectTooManyRequestsError as e:
        print(
            f"Rate limited by Garmin after {len(probe.calls)} calls: {e}",
            file=sys.stderr,
        )
        return 2

    report = build_report(
        probe, login_method, args.days, args.history_days, recent, history, samples
    )
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print_report(report, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
