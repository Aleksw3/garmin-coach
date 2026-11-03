# Garmin coach

A self-hosted training coach. It syncs Garmin data to a home server and uses Claude to plan training, give feedback on sessions and keep a library of training research. Each person in the household has a profile, and the research library is shared. The plan and the phases are in [docs/PLAN.md](docs/PLAN.md).

## Setup

You need [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`), Node 20 or newer, and an Anthropic API key from https://platform.claude.com.

1. Clone the repo and create a `.env` file at the repo root:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   MONTHLY_BUDGET_USD=5
   ```
2. Build the web UI:
   ```
   cd frontend
   npm install
   npm run build
   cd ..
   ```
3. Create a profile for each person. The name is lowercase and is used in paths. Use `--trimp 1.92` for men and `1.67` for women.
   ```
   cd backend
   uv run coach profile add kari --name Kari --trimp 1.67
   ```
4. Log in to Garmin for each profile. It asks for the email, password and 2FA code, and saves tokens so later syncs don't need them.
   ```
   uv run coach -p kari login
   ```
5. Fetch the history. Two years takes a while, and the command resumes where it stopped if it is interrupted.
   ```
   uv run coach -p kari backfill --days 730
   ```
6. Start the server. It serves the app on http://127.0.0.1:8000 and syncs every profile with Garmin each hour from 05:00 to 23:00.
   ```
   uv run coach serve
   ```
   Use `--host 0.0.0.0` to reach it from other machines on the VPN. The app has no login, so anyone who can reach it sees every profile.
7. In the app, pick your profile and set it up:
   - On Goals, add your goals and check the TRIMP factor.
   - On Trends, add your LT1 and LT2 heart rates to get your zones.
   - On Settings, enter an [ntfy](https://ntfy.sh) topic to get the coach's messages on your phone. Pick a long name that is hard to guess and subscribe to it in the ntfy app.
   - On Research, press Fetch now and approve the papers you want the coach to use.

Restart the server after adding a profile. Run only one of `coach serve`, a manual `coach backfill` or the Docker container against the same `data/` at a time, so two syncs don't talk to Garmin at once.

### With Docker

Steps 1 and 7 are the same. The image builds the web UI, and `data/` is mounted into the container.

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
