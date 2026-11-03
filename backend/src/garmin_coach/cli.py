import argparse
import getpass
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
from garmin_coach.garmin.connect import GarminConnectSource
from garmin_coach.garmin.source import GarminAuthError, GarminRateLimited
from garmin_coach.metrics.load import trimp_for
from garmin_coach.metrics.summary import format_metrics
from garmin_coach.models import Activity, DailyWellness, SyncRun
from garmin_coach.normalize import rebuild_all
from garmin_coach.normalize.sports import unmapped_type_keys
from garmin_coach.profiles import (
    ProfileError,
    adopt_single_database,
    athlete,
    create_profile,
    open_profile,
    open_research,
    profile_name,
    profile_slugs,
)
from garmin_coach.reports import format_weekly_totals, week_start, weekly_totals
from garmin_coach.sync import BACKFILL_CURSOR, LAST_SYNC, SyncService, get_state


def chosen_profile(args: argparse.Namespace) -> str:
    settings = get_settings()
    slugs = profile_slugs(settings)
    if args.profile:
        return str(args.profile)
    if len(slugs) == 1:
        return slugs[0]
    if not slugs and settings.single_database_path.exists():
        raise ProfileError(
            "The data is still in the old single-person layout. "
            "Move it into a profile with: coach profile adopt <name>"
        )
    if not slugs:
        raise ProfileError("No profiles yet. Create one with: coach profile add <name>")
    raise ProfileError(f"Choose a profile with --profile: {', '.join(slugs)}")


def open_database(args: argparse.Namespace) -> sessionmaker[Session]:
    return open_profile(get_settings(), chosen_profile(args))


def garmin_mfa() -> str:
    return input("Garmin MFA code: ").strip()


def sync_service(
    slug: str,
    sessions: sessionmaker[Session],
    email: str | None = None,
    password: str | None = None,
) -> SyncService:
    settings = get_settings()
    source = GarminConnectSource(
        settings.profile_tokens_dir(slug),
        email,
        password,
        prompt_mfa=garmin_mfa,
    )
    return SyncService(
        source,
        sessions,
        settings.garmin_request_delay,
        recent_days=settings.recent_sync_days,
        refresh_days=settings.daily_refresh_days,
    )


def profile_sync_service(args: argparse.Namespace) -> SyncService:
    slug = chosen_profile(args)
    return sync_service(slug, open_profile(get_settings(), slug))


def command_login(args: argparse.Namespace) -> None:
    slug = chosen_profile(args)
    email = input(f"Garmin email for {slug}: ").strip()
    password = getpass.getpass("Garmin password: ")
    tokens = get_settings().profile_tokens_dir(slug)
    GarminConnectSource(tokens, email, password, prompt_mfa=garmin_mfa).login()
    print(f"Logged in. The tokens are in {tokens}")


def command_profile_add(args: argparse.Namespace) -> None:
    settings = get_settings()
    create_profile(settings, args.slug, args.name, args.trimp or settings.trimp_coefficient)
    print(f"Created profile {args.slug}. Log in to Garmin with: coach -p {args.slug} login")


def command_profile_list(args: argparse.Namespace) -> None:
    settings = get_settings()
    for slug in profile_slugs(settings):
        with open_profile(settings, slug)() as session:
            print(f"{slug}: {profile_name(session, slug)}")


def command_profile_adopt(args: argparse.Namespace) -> None:
    settings = get_settings()
    moved = adopt_single_database(
        settings, args.slug, settings.ntfy_topic, settings.trimp_coefficient
    )
    print(
        f"Moved the data into profile {args.slug} and {moved} research papers into "
        f"{settings.research_database_path}"
    )


def command_sync(args: argparse.Namespace) -> None:
    result = profile_sync_service(args).sync_recent()
    print(f"Synced {result.activities} activities and {result.days} days in {result.calls} calls")


def command_backfill(args: argparse.Namespace) -> None:
    result = profile_sync_service(args).backfill(args.days, restart=args.restart)
    print(
        f"Backfill done: {result.activities} activities, {result.days} days, "
        f"{result.calls} calls, {result.failed_calls} failed"
    )


def command_rebuild(args: argparse.Namespace) -> None:
    sessions = open_database(args)
    with sessions() as session:
        activities, days = rebuild_all(session)
        session.commit()
    print(f"Rebuilt {activities} activities and {days} days from raw data")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def command_import_probe(args: argparse.Namespace) -> None:
    probe_dir: Path = args.probe_dir
    sessions = open_database(args)
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
    sessions = open_database(args)
    last = week_start(args.end)
    first = last - timedelta(weeks=args.weeks - 1)
    with sessions() as session:
        print(format_weekly_totals(weekly_totals(session, first, last)))


def command_status(args: argparse.Namespace) -> None:
    sessions = open_database(args)
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
    sessions = open_database(args)
    with sessions() as session:
        trimp = trimp_for(session, get_settings().trimp_coefficient)
        print(format_metrics(session, args.weeks, args.end, trimp))


def command_structure_sessions(args: argparse.Namespace) -> None:
    import anthropic

    from garmin_coach.coach.structure import SessionStructurer, unstructured

    settings = get_settings()
    if not settings.anthropic_api_key:
        print("Set ANTHROPIC_API_KEY in .env first", file=sys.stderr)
        return
    structurer = SessionStructurer(
        anthropic.Anthropic(api_key=settings.anthropic_api_key).messages.create,
        settings.background_model,
    )
    sessions = open_database(args)
    with sessions() as session:
        rows = unstructured(session)
        for row in rows:
            result = structurer.apply(session, row)
            print(
                f"{row.day} {row.title}: {len(result.steps)} steps, "
                f"{len(result.exercises)} exercises"
            )
            session.commit()
    print(f"Structured {len(rows)} sessions")


def command_serve(args: argparse.Namespace) -> None:
    import anthropic
    import uvicorn

    from garmin_coach.api.app import create_app
    from garmin_coach.api.profile import ProfileRuntime, make_profile
    from garmin_coach.coach.agent import Coach, anthropic_stream_factory, coach_settings
    from garmin_coach.coach.notify import Notifier, ProfileNotifier
    from garmin_coach.coach.proactive import ProactiveCoach
    from garmin_coach.coach.usage import Spending
    from garmin_coach.evidence.fetch import EvidenceFetcher
    from garmin_coach.evidence.pubmed import PubMed
    from garmin_coach.evidence.summarize import Summarizer
    from garmin_coach.jobs import Schedule

    settings = get_settings()
    slugs = profile_slugs(settings)
    if not slugs:
        chosen_profile(args)
    research = open_research(settings)
    databases = {slug: open_profile(settings, slug) for slug in slugs}
    spending = Spending([research, *databases.values()])
    key = settings.anthropic_api_key
    stream_factory = anthropic_stream_factory(key) if key else None
    base_notifier = Notifier(settings.ntfy_url, None, settings.ntfy_token, settings.app_url)

    def runtime(slug: str, sessions: sessionmaker[Session]) -> ProfileRuntime:
        def read_topic() -> str | None:
            with sessions() as session:
                return athlete(session).ntfy_topic

        coach = Coach(
            sessions,
            stream_factory,
            coach_settings(settings),
            research=research,
            spending=spending,
        )
        notifier = ProfileNotifier(base_notifier, slug, read_topic)
        window = timedelta(hours=settings.feedback_window_hours)
        proactive = ProactiveCoach(sessions, coach, notifier, window) if key else None
        return make_profile(
            slug, sessions, lambda: sync_service(slug, sessions), coach, proactive, notifier
        )

    fetcher = (
        EvidenceFetcher(
            research,
            PubMed(),
            Summarizer(anthropic.Anthropic(api_key=key).messages.create, settings.background_model),
            settings.monthly_budget_usd,
            spending=spending,
        )
        if key
        else None
    )
    app = create_app(
        [runtime(slug, sessions) for slug, sessions in databases.items()],
        research,
        frontend_dir=settings.frontend_dir,
        schedule_sync=not args.no_schedule,
        schedule=Schedule(
            settings.checkin_time,
            settings.review_day,
            settings.review_time,
            settings.evidence_day,
            settings.evidence_time,
        ),
        evidence_fetcher=fetcher,
    )
    uvicorn.run(app, host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coach")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-p", "--profile", help="the profile to use when there are several")
    commands = parser.add_subparsers(required=True)

    login = commands.add_parser("login", help="log in to Garmin and save the tokens")
    login.set_defaults(run=command_login)

    profile = commands.add_parser("profile", help="add, list or adopt profiles")
    profile_commands = profile.add_subparsers(required=True)
    add = profile_commands.add_parser("add", help="create an empty profile")
    add.add_argument("slug", help="lowercase name used in paths, for example kari")
    add.add_argument("--name", help="display name")
    add.add_argument("--trimp", type=float, help="TRIMP factor, 1.92 for men, 1.67 for women")
    add.set_defaults(run=command_profile_add)
    listing = profile_commands.add_parser("list", help="list the profiles")
    listing.set_defaults(run=command_profile_list)
    adopt = profile_commands.add_parser(
        "adopt", help="move the old single-person data into a profile"
    )
    adopt.add_argument("slug")
    adopt.set_defaults(run=command_profile_adopt)

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

    serve = commands.add_parser("serve", help="run the web app and the hourly sync")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-schedule", action="store_true", help="don't sync on a schedule")
    serve.set_defaults(run=command_serve)

    structure = commands.add_parser(
        "structure-sessions", help="split old session texts into steps and exercises"
    )
    structure.set_defaults(run=command_structure_sessions)

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
    except ProfileError as e:
        print(e, file=sys.stderr)
        return 1
    return 0
