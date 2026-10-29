# Garmin coach

A self-hosted training coach that syncs Garmin data to a home server (a Raspberry Pi in the end) and plans training with Claude. See [docs/PLAN.md](docs/PLAN.md).

## Backend

The backend in `backend/` is a Python package managed with [uv](https://docs.astral.sh/uv/). It stores everything in `data/coach.db` (SQLite) and reuses the Garmin tokens in `data/garmin_tokens/`. Each command applies database migrations before it runs.

```
cd backend
uv run coach sync                  # fetch the last 14 days, refetching the last 3
uv run coach backfill --days 730   # fetch 2 years of history, resumes where it stopped
uv run coach weeks --weeks 4       # weekly distance, time and climbing per sport group
uv run coach status                # counts, last sync runs, unmapped activity types
uv run coach rebuild               # rebuild the core tables from the stored raw JSON
uv run coach import-probe ../data/probe/<timestamp>   # load a probe dump without calling Garmin
```

Settings come from environment variables or a `.env` file at the repo root: `DATA_DIR`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `GARMIN_REQUEST_DELAY` (seconds between requests, default 2).

Development checks:

```
cd backend
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src tests
```

## Phase 0: Garmin probe

`scripts/garmin_probe.py` checks that Garmin login and data pulls work on a machine. It needs [uv](https://docs.astral.sh/uv/), which installs Python 3.12+ and the script's dependencies on first run.

```
./scripts/garmin_probe.py
```

On a machine without uv, install it first with `curl -LsSf https://astral.sh/uv/install.sh | sh`.

The first run asks for your Garmin email, password and, if enabled, the 2FA code. It saves tokens to `data/garmin_tokens/`, so the next runs log in without them. You can also set `GARMIN_EMAIL` and `GARMIN_PASSWORD` in the environment.

The script pulls 7 days of activities, activity details and daily wellness data, plus one example of each sport from the last 2 years. It saves the raw JSON under `data/probe/<timestamp>/` and prints a report: activity types found, checks for strength sets, run elevation, ski touring, sleep and HRV, failed calls, and an estimate of how long a 24-month backfill takes.

Phase 0 is done when two runs in a row log in with saved tokens and all checks pass. `data/` is in `.gitignore` because it holds tokens and personal data.
