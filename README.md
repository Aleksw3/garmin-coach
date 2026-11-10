# Garmin coach

A self-hosted training coach. It syncs Garmin data to a home server and uses Claude to plan training, give feedback on sessions and keep a library of training research. Each person in the household has a profile, and the research library is shared. The plan and the phases are in [docs/PLAN.md](docs/PLAN.md).

## Setup

1. Get an Anthropic API key with credits. The API is prepaid and separate from a Claude.ai Pro or Max subscription, so the coach does nothing until the account has credits. The setup in the app shows these steps too.
   1. Sign in or create an account at https://platform.claude.com.
   2. Open Settings > Billing and press Buy credits. Credits expire a year after you buy them. Leave auto-reload off to make the credits you bought the most you can ever spend. The app also has its own monthly budget.
   3. Open Settings > API keys and press Create key. Copy the key right away, because the console shows it only once. It starts with `sk-ant-`.
2. Run the install script from the repo root:
   ```
   ./scripts/install.sh
   ```
   - It installs uv and Node into your home folder if they are missing or too old. Raspberry Pi OS Bookworm ships Node 18, which is too old.
   - It installs the Python packages and builds the web UI.
   - It starts the app as a systemd service for your user, so it runs at boot and restarts if it crashes. It asks whether other devices on the network should reach it, and offers to turn on systemd lingering with sudo so the service starts without a login.

   Run it again after a `git pull` to rebuild and restart.
3. Open the address the script prints, for example http://raspberrypi.local:8000. The first visit walks you through:
   - the API key and the monthly budget, shared by everyone;
   - your name and training load factor;
   - the Garmin Connect login, including the two-step code if your account uses one;
   - how much history to fetch. The fetch runs in the background, and Settings shows how far it has come.
4. In the app, finish setting up:
   - On Goals, add your goals. A race goal takes the course as a GPX file, so the coach knows the climbs and descents.
   - On Trends, add your LT1 and LT2 heart rates to get your zones.
   - On Settings, enter an [ntfy](https://ntfy.sh) topic to get the coach's messages on your phone. Pick a long name that is hard to guess and subscribe to it in the ntfy app.
   - On Research, press Fetch now and approve the papers you want the coach to use.

To add another person, use Add another person on Settings, or Add a person on the profile picker. The app has no login, so anyone who can reach it sees every profile.

### Running the service

```
systemctl --user status garmin-coach     # is it running?
journalctl --user -u garmin-coach -f     # follow the log
systemctl --user restart garmin-coach
systemctl --user stop garmin-coach
```

Run only one coach against the same `data/` at a time, so two syncs don't talk to Garmin at once. `scripts/copy-to-pi.sh <user@host>` moves the profiles and the research library from one machine to another over ssh.

### Without the script

Build the web UI, start the server, and open http://127.0.0.1:8000:

```
cd frontend && npm install && npm run build && cd ..
cd backend
uv run coach serve --host 0.0.0.0
```

### With Docker

The image builds the web UI, and `data/` is mounted into the container. Start it and open http://127.0.0.1:8000. `compose.yaml` only listens on 127.0.0.1, so change the port line to `"8000:8000"` to reach it from other devices.

```
docker compose up -d --build
docker compose logs -f
```

## Commands

The app covers the setup, but these still work from `backend/`. With one profile, `-p` is optional.

| Command | What it does |
|---|---|
| `coach profile add kari --name Kari --trimp 1.67` | adds a profile; restart the service afterwards |
| `coach -p kari login` | logs in to Garmin and saves the token |
| `coach -p kari backfill --days 730` | fetches history; it continues where it stopped |
| `coach profile list` | lists the profiles |
| `coach -p kari sync` | fetches the last 14 days and refetches the last 3 |
| `coach -p kari weeks --weeks 4` | prints weekly distance, time and climbing per sport group |
| `coach -p kari metrics` | prints load, HRV and resting HR against their baselines |
| `coach -p kari status` | prints counts, the last sync runs and unmapped activity types |
| `coach backup` | copies every database to a dated folder in the backup folder, as the nightly job does |
| `coach -p kari rebuild` | rebuilds the core tables from the stored raw JSON |
| `coach -p kari structure-sessions` | splits old planned session texts into steps and exercises |
| `coach profile adopt kari` | moves the old single-person `data/coach.db` into a profile |

## Settings

All settings are optional. Put them in `.env` at the repo root or in the environment, and restart the service. A key and budget saved on the Settings page take priority over the values here.

| Setting | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | turns on the coach |
| `MONTHLY_BUDGET_USD` | 5 | caps API cost for all profiles and research together; coach calls stop until the 1st when it is reached |
| `CHAT_MODEL`, `CHAT_EFFORT` | `claude-sonnet-5-5`, `low` | the chat model |
| `PLAN_MODEL`, `PLAN_EFFORT` | `claude-opus-5-5`, `high` | the model that builds training plans |
| `BACKGROUND_MODEL` | `claude-haiku-5-5` | writes check-ins, activity feedback and paper summaries |
| `CHECKIN_TIME` | `06:30` | the morning check-in. It syncs first and waits up to 2 hours for the watch to upload last night |
| `REVIEW_DAY`, `REVIEW_TIME` | `sun`, `19:00` | the weekly review |
| `WATCH_TIME` | `20:00` | sends tomorrow's planned sessions to the Garmin calendar so the watch has them in the morning |
| `FEEDBACK_WINDOW_HOURS` | 36 | how old a new activity can be and still get feedback |
| `EVIDENCE_DAY`, `EVIDENCE_TIME` | `mon`, `07:00` | the weekly PubMed fetch |
| `NTFY_URL`, `NTFY_TOKEN` | `https://ntfy.sh`, none | a self-hosted ntfy server |
| `APP_URL` | none | the address a tap on a notification opens |
| `DATA_DIR` | `data/` | where databases and Garmin tokens live |
| `BACKUP_TIME`, `BACKUP_KEEP_DAYS` | `03:30`, 14 | when the nightly backup runs and how many days it keeps |
| `BACKUP_DIR` | `data/backups/` | where the backups go; point it at another disk or a NAS mount to survive a dead disk |
| `GARMIN_REQUEST_DELAY` | 2 | seconds between Garmin requests |

Each profile keeps its database and Garmin tokens in `data/profiles/<name>/`. The research library, the API key and the budget are in `data/research.db`, which only your user can read. `data/` is in `.gitignore` because it holds tokens and personal data.

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
