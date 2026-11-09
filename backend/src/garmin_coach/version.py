import subprocess

from pydantic import BaseModel

from garmin_coach.config import REPO_ROOT


class Version(BaseModel):
    commit: str | None = None
    committed_at: str | None = None
    subject: str | None = None


def running_version() -> Version:
    """Read once at startup, so it names the code this process runs even after a later git pull."""
    try:
        output = subprocess.run(
            ["git", "log", "-1", "--format=%h%x00%cI%x00%s"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return Version()
    commit, committed_at, subject = output.strip().split("\0")
    return Version(commit=commit, committed_at=committed_at, subject=subject)
