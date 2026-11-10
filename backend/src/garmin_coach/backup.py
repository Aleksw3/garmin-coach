import logging
import shutil
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from garmin_coach.config import Settings
from garmin_coach.profiles import profile_slugs

log = logging.getLogger(__name__)


def copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    unfinished = target.with_name(target.name + ".part")
    unfinished.unlink(missing_ok=True)
    with closing(sqlite3.connect(source)) as live, closing(sqlite3.connect(unfinished)) as copy:
        live.backup(copy)
    unfinished.chmod(0o600)
    unfinished.replace(target)


def databases(settings: Settings) -> list[Path]:
    paths = [settings.profile_database_path(slug) for slug in profile_slugs(settings)]
    if settings.research_database_path.exists():
        paths.append(settings.research_database_path)
    return paths


def remove_old(backup_dir: Path, today: date, keep_days: int) -> list[Path]:
    removed = []
    for folder in backup_dir.iterdir():
        try:
            day = date.fromisoformat(folder.name)
        except ValueError:
            continue
        if folder.is_dir() and day <= today - timedelta(days=keep_days):
            shutil.rmtree(folder)
            removed.append(folder)
    return removed


def backup_all(settings: Settings, today: date | None = None) -> Path:
    today = today or date.today()
    folder = settings.backup_path / today.isoformat()
    for source in databases(settings):
        copy_database(source, folder / source.relative_to(settings.data_dir))
    remove_old(settings.backup_path, today, settings.backup_keep_days)
    log.info("Backed up the databases to %s", folder)
    return folder
