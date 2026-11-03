# Garmin coach

A self-hosted training coach. It syncs Garmin data to a home server and uses Claude to plan training, give feedback on sessions and keep a library of training research. Each person in the household has a profile, and the research library is shared. The plan and the phases are in [docs/PLAN.md](docs/PLAN.md).

## Setup

1. Get an Anthropic API key with credits. The API is prepaid and separate from a Claude.ai Pro or Max subscription, so the coach does nothing until the account has credits.
   1. Sign in or create an account at https://platform.claude.com.
   2. Open Settings > Billing and press Buy credits. Credits expire a year after you buy them. Leave auto-reload off to make the credits you bought the most you can ever spend. The app also has its own monthly budget, set in the next step.
   3. Open Settings > API keys and press Create key. Copy the key right away, because the console shows it only once. It starts with `sk-ant-`.
2. Run the install script from the repo root:
   ```
   ./scripts/install.sh
   ```
   It explains each step and asks for what it needs:
   - It installs uv and Node into your home folder if they are missing or too old. Raspberry Pi OS Bookworm ships Node 18, which is too old.
   - It asks for the API key, checks it against Anthropic and saves it in `.env`.
   - It asks for the monthly budget in dollars, shared by all profiles and the research library.
   - It installs the Python packages and builds the web UI.
   - For each person, it asks for a short name, a display name and the TRIMP factor (1.92 for men, 1.67 for women). It then logs in to Garmin and asks how many days of history to fetch.

   Run it again later to add a profile or to change the key or budget.
3. Start the server. It serves the app on http://127.0.0.1:8000 and syncs every profile with Garmin each hour from 05:00 to 23:00.
   ```
   cd backend
   uv run coach serve
   ```
   Use `--host 0.0.0.0` to reach it from other machines on the VPN. The app has no login, so anyone who can reach it sees every profile.
4. In the app, pick your profile and set it up:
   - On Goals, add your goals and check the TRIMP factor.
   - On Trends, add your LT1 and LT2 heart rates to get your zones.
   - On Settings, enter an [ntfy](https://ntfy.sh) topic to get the coach's messages on your phone. Pick a long name that is hard to guess and subscribe to it in the ntfy app.
   - On Research, press Fetch now and approve the papers you want the coach to use.

Restart the server after adding a profile. Run only one of `coach serve`, a manual `coach backfill` or the Docker container against the same `data/` at a time, so two syncs don't talk to Garmin at once.

### Without the script

Put `ANTHROPIC_API_KEY=sk-ant-...` and `MONTHLY_BUDGET_USD=5` in a `.env` file at the repo root, then:

```
cd frontend && npm install && npm run build && cd ..
cd backend
uv run coach profile add kari --name Kari --trimp 1.67
uv run coach -p kari login
uv run coach -p kari backfill --days 730
```

The backfill takes a couple of hours for two years. If it stops, the same command continues where it left off.

### With Docker

Steps 1 and 4 are the same. Write `.env` by hand as described under "Without the script". The image builds the web UI, and `data/` is mounted into the container.

```
docker compose build
docker compose run --rm app coach profile add kari --name Kari --trimp 1.67
docker compose run --rm app coach -p kari login
docker compose run --rm app coach -p kari backfill --days 730
docker compose up -d
```

To add a profile later, stop the container with `docker compose down` first, then run the profile commands and start it again.

## Commands

Run these from `backend/`. With one profile, `-p` is optional.

| Command | What it does |
|---|---|
| `coach profile list` | lists the profiles |
| `coach -p kari sync` | fetches the last 14 days and refetches the last 3 |
| `coach -p kari weeks --weeks 4` | prints weekly distance, time and climbing per sport group |
| `coach -p kari metrics` | prints load, HRV and resting HR against their baselines |
| `coach -p kari status` | prints counts, the last sync runs and unmapped activity types |
| `coach -p kari rebuild` | rebuilds the core tables from the stored raw JSON |
| `coach -p kari structure-sessions` | splits old planned session texts into steps and exercises |
| `coach profile adopt kari` | moves the old single-person `data/coach.db` into a profile |

## Settings

All settings are optional except the API key. Put them in `.env` or the environment.

| Setting | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | turns on the coach |
| `MONTHLY_BUDGET_USD` | 5 | caps API cost for all profiles and research together; coach calls stop until the 1st when it is reached |
| `CHAT_MODEL`, `CHAT_EFFORT` | `claude-sonnet-5-5`, `low` | the chat model |
| `PLAN_MODEL`, `PLAN_EFFORT` | `claude-opus-5-5`, `high` | the model that builds training plans |
| `BACKGROUND_MODEL` | `claude-haiku-5-5` | writes check-ins, activity feedback and paper summaries |
| `CHECKIN_TIME` | `06:30` | the morning check-in |
| `REVIEW_DAY`, `REVIEW_TIME` | `sun`, `19:00` | the weekly review |
| `FEEDBACK_WINDOW_HOURS` | 36 | how old a new activity can be and still get feedback |
| `EVIDENCE_DAY`, `EVIDENCE_TIME` | `mon`, `07:00` | the weekly PubMed fetch |
| `NTFY_URL`, `NTFY_TOKEN` | `https://ntfy.sh`, none | a self-hosted ntfy server |
| `APP_URL` | none | the address a tap on a notification opens |
| `DATA_DIR` | `data/` | where databases and Garmin tokens live |
| `GARMIN_REQUEST_DELAY` | 2 | seconds between Garmin requests |

Each profile keeps its database and Garmin tokens in `data/profiles/<name>/`. The research library is in `data/research.db`. `data/` is in `.gitignore` because it holds tokens and personal data.

## Development

Run `uv run coach serve` and `npm run dev` side by side. Vite serves the UI on http://localhost:5173 and proxies `/api` to port 8000.

```
cd backend
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src tests

cd ../frontend
npm run lint
```

`scripts/garmin_probe.py` checks that Garmin login and data pulls work on a new machine, and saves the raw JSON under `data/probe/`. `coach import-probe <dir>` loads such a dump without calling Garmin.
