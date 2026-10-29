import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from garmin_coach import raw_store
from garmin_coach.config import get_settings
from garmin_coach.db import create_db_engine, session_factory
from garmin_coach.garmin.connect import GarminConnectSource
from garmin_coach.garmin.source import GarminAuthError, GarminRateLimited
from garmin_coach.metrics.summary import format_metrics
from garmin_coach.migrate import upgrade_database
from garmin_coach.models import Activity, DailyWellness, SyncRun
from garmin_coach.normalize import rebuild_all
from garmin_coach.normalize.sports import seed_sport_mapping, unmapped_type_keys
from garmin_coach.reports import format_weekly_totals, week_start, weekly_totals
from garmin_coach.sync import BACKFILL_CURSOR, LAST_SYNC, SyncService, get_state


def open_database() -> sessionmaker[Session]:
    settings = get_settings()
    upgrade_database(settings.database_url)
    sessions = session_factory(create_db_engine(settings.database_url))
    with sessions() as session:
        seed_sport_mapping(session)
        session.commit()
    return sessions


def sync_service(sessions: sessionmaker[Session]) -> SyncService:
    settings = get_settings()
    source = GarminConnectSource(
        settings.garmin_tokens_dir,
        settings.garmin_email,
        settings.garmin_password,
        prompt_mfa=lambda: input("Garmin MFA code: ").strip(),
    )
    return SyncService(
        source,
        sessions,
        settings.garmin_request_delay,
        recent_days=settings.recent_sync_days,
        refresh_days=settings.daily_refresh_days,
    )


def command_sync(args: argparse.Namespace) -> None:
    result = sync_service(open_database()).sync_recent()
    print(f"Synced {result.activities} activities and {result.days} days in {result.calls} calls")


def command_backfill(args: argparse.Namespace) -> None:
    result = sync_service(open_database()).backfill(args.days, restart=args.restart)
    print(
        f"Backfill done: {result.activities} activities, {result.days} days, "
        f"{result.calls} calls, {result.failed_calls} failed"
    )


def command_rebuild(args: argparse.Namespace) -> None:
    sessions = open_database()
    with sessions() as session:
        activities, days = rebuild_all(session)
        session.commit()
    print(f"Rebuilt {activities} activities and {days} days from raw data")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def command_import_probe(args: argparse.Namespace) -> None:
    probe_dir: Path = args.probe_dir
    sessions = open_database()
    with sessions() as session:
        summaries: dict[int, Any] = {}
        for name in ("list_history.json", "list_recent.json"):
            path = probe_dir / "activities" / name
            if path.exists():
                summaries |= {item["activityId"]: item for item in read_json(path)}
        for activity_id, summary in summaries.items():
            raw_store.put_activity(session, activity_id, "summary", summary)
            for endpoint_file in (probe_dir / "activities" / str(activity_id)).glob("*.json"):
                if endpoint_file.stem != "activity":
                    raw_store.put_activity(
                        session, activity_id, endpoint_file.stem, read_json(endpoint_file)
                    )
        days = sorted((probe_dir / "daily").iterdir()) if (probe_dir / "daily").exists() else []
        for day_dir in days:
            for kind_file in day_dir.glob("*.json"):
                raw_store.put_daily(
                    session, date.fromisoformat(day_dir.name), kind_file.stem, read_json(kind_file)
                )
        body_composition = probe_dir / "body_composition.json"
        if body_composition.exists() and days:
            raw_store.put_daily(
                session,
                date.fromisoformat(days[-1].name),
                "body_composition",
                read_json(body_composition),
            )
        activities, normalized_days = rebuild_all(session)
        session.commit()
    print(f"Imported {activities} activities and {normalized_days} days from {probe_dir}")


def command_weeks(args: argparse.Namespace) -> None:
    sessions = open_database()
    last = week_start(args.end)
    first = last - timedelta(weeks=args.weeks - 1)
    with sessions() as session:
        print(format_weekly_totals(weekly_totals(session, first, last)))


def command_status(args: argparse.Namespace) -> None:
    sessions = open_database()
    with sessions() as session:
        activities = session.scalar(select(func.count()).select_from(Activity))
        days = session.scalar(select(func.count()).select_from(DailyWellness))
        oldest = session.scalar(select(func.min(Activity.local_date)))
        print(f"Activities: {activities} (oldest {oldest}), days with wellness data: {days}")
        print(f"Last sync: {get_state(session, LAST_SYNC) or 'never'}")
        print(f"Backfill reached: {get_state(session, BACKFILL_CURSOR) or 'not started'}")
        runs = session.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(5))
        for run in runs:
            print(
                f"  {run.started_at:%Y-%m-%d %H:%M} {run.kind:8s} {run.status:12s} "
                f"{run.calls} calls, {run.failed_calls} failed {run.error or ''}"
            )
        unmapped = unmapped_type_keys(session)
        if unmapped:
            print(f"Activity types without a sport group: {', '.join(unmapped)}")


def command_metrics(args: argparse.Namespace) -> None:
    sessions = open_database()
    with sessions() as session:
        print(format_metrics(session, args.weeks, args.end, get_settings().trimp_coefficient))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coach")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(required=True)

    sync = commands.add_parser("sync", help="fetch recent Garmin data")
    sync.set_defaults(run=command_sync)

    backfill = commands.add_parser("backfill", help="fetch Garmin history, resumable")
    backfill.add_argument("--days", type=int, default=730)
    backfill.add_argument("--restart", action="store_true", help="ignore the saved position")
    backfill.set_defaults(run=command_backfill)

    rebuild = commands.add_parser("rebuild", help="rebuild core tables from raw data")
    rebuild.set_defaults(run=command_rebuild)

    import_probe = commands.add_parser("import-probe", help="load a garmin_probe.py dump")
    import_probe.add_argument("probe_dir", type=Path)
    import_probe.set_defaults(run=command_import_probe)

    weeks = commands.add_parser("weeks", help="weekly totals per sport group")
    weeks.add_argument("--weeks", type=int, default=4)
    weeks.add_argument("--end", type=date.fromisoformat, default=date.today())
    weeks.set_defaults(run=command_weeks)

    metrics = commands.add_parser("metrics", help="load, recovery, running and strength")
    metrics.add_argument("--weeks", type=int, default=4)
    metrics.add_argument("--end", type=date.fromisoformat, default=date.today())
    metrics.set_defaults(run=command_metrics)

    status = commands.add_parser("status", help="database and sync status")
    status.set_defaults(run=command_status)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.getLogger("alembic").setLevel(logging.WARNING)
    try:
        args.run(args)
    except GarminRateLimited as e:
        print(f"Garmin rate limited the sync. Run it again later to resume. ({e})", file=sys.stderr)
        return 2
    except GarminAuthError as e:
        print(f"Garmin login failed: {e}", file=sys.stderr)
        return 1
    return 0
