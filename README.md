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

Settings come from environment variables or a `.env` file at the repo root: `DATA_DIR`, `FRONTEND_DIR`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `GARMIN_REQUEST_DELAY` (seconds between requests, default 2), `TRIMP_COEFFICIENT` (1.92 by default, the value Banister used for men; 1.67 is the value for women). TRIMP only fills in load for activities where Garmin has none.

The coach chat needs `ANTHROPIC_API_KEY` from https://platform.claude.com. `CHAT_MODEL` (default `claude-sonnet-5-5`) and `CHAT_EFFORT` (default `low`) pick the model and how much it thinks. `PLAN_MODEL` (default `claude-opus-5-5`, effort `PLAN_EFFORT`, default `high`) builds training plans, and `BACKGROUND_MODEL` (default `claude-haiku-5-5`) writes the morning check-in and activity feedback. `MONTHLY_BUDGET_USD` (default 5) caps the API cost: when a month's spending reaches it, every coach call stops until the 1st. Each API call's tokens and cost are logged in the `api_usage` table and shown on the Settings page.

With an API key set, `coach serve` also runs the proactive coach. It writes a morning check-in at `CHECKIN_TIME` (default `06:30`), feedback after each sync that brings in a new activity from the last `FEEDBACK_WINDOW_HOURS` (default 36), and a weekly review on `REVIEW_DAY` at `REVIEW_TIME` (default `sun` at `19:00`). The messages go to a "Coach, week from ..." thread in Chat. To get them on your phone, install the [ntfy](https://ntfy.sh) app, pick a long topic name that is hard to guess, subscribe to it, and set `NTFY_TOPIC` to the same name. `NTFY_URL` (default `https://ntfy.sh`) and `NTFY_TOKEN` point it at a self-hosted server, and `APP_URL` makes a tap on a notification open the app. A failed Garmin login also sends a notification.

`uv run coach metrics` prints load, HRV and resting HR against their baselines, running weeks and strength volume. `uv run coach serve` runs the web app on http://127.0.0.1:8000 and syncs with Garmin at 5 minutes past every hour from 05:00 to 23:00 (`--no-schedule` turns that off).

## Frontend

The web UI in `frontend/` is React, Vite, Tailwind and ECharts. It has six pages in the menu: Today, Chat, Plan (proposals and the calendar), Trends, Goals (goals, profile and the coach's notes) and Settings (API cost and notifications). Each activity has its own page at `#activity/<id>` with laps, HR zones and the strength set editor. `npm run build` writes `frontend/dist`, which `coach serve` serves. For development, run `coach serve` and `npm run dev` side by side; Vite proxies `/api` to port 8000.

```
cd frontend
npm install
npm run dev       # http://localhost:5173
npm run build
npm run lint
```

## Docker

`compose.yaml` builds the frontend and backend into one image and runs it with `data/` mounted, as your own user, on 127.0.0.1:8000.

```
docker compose up -d --build
docker compose logs -f
```

Run only one of `coach serve`, a manual `coach backfill`, or the container against the same `data/` at a time, so two syncs don't talk to Garmin at once.

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
