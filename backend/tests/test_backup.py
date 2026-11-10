import sqlite3
from datetime import date
from pathlib import Path

from garmin_coach.backup import backup_all
from garmin_coach.config import Settings
from garmin_coach.profiles import create_profile, open_research


def make_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, backup_keep_days=2, _env_file=None)  # type: ignore[call-arg]


def test_backup_copies_every_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    create_profile(settings, "kari", "Kari", 1.67)
    open_research(settings)

    folder = backup_all(settings, date(2026, 11, 10))

    assert folder == tmp_path / "backups" / "2026-11-10"
    copy = sqlite3.connect(folder / "profiles" / "kari" / "coach.db")
    assert copy.execute("SELECT name FROM athlete_profile").fetchone() == ("Kari",)
    assert (folder / "research.db").exists()
    assert not list(folder.rglob("*.part"))


def test_backup_keeps_only_the_newest_days(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    create_profile(settings, "kari", "Kari", 1.67)
    for day in (7, 8, 9, 10):
        backup_all(settings, date(2026, 11, day))
    (tmp_path / "backups" / "notes").mkdir()

    kept = sorted(path.name for path in (tmp_path / "backups").iterdir())

    assert kept == ["2026-11-09", "2026-11-10", "notes"]
