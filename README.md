# Garmin coach

A self-hosted training coach that syncs Garmin data to a home server (a Raspberry Pi in the end) and plans training with Claude. See [docs/PLAN.md](docs/PLAN.md).

## Phase 0: Garmin probe

`scripts/garmin_probe.py` checks that Garmin login and data pulls work on a machine. It needs [uv](https://docs.astral.sh/uv/), which installs Python 3.12+ and the script's dependencies on first run.

```
./scripts/garmin_probe.py
```

On a machine without uv, install it first with `curl -LsSf https://astral.sh/uv/install.sh | sh`.

The first run asks for your Garmin email, password and, if enabled, the 2FA code. It saves tokens to `data/garmin_tokens/`, so the next runs log in without them. You can also set `GARMIN_EMAIL` and `GARMIN_PASSWORD` in the environment.

The script pulls 7 days of activities, activity details and daily wellness data, plus one example of each sport from the last 2 years. It saves the raw JSON under `data/probe/<timestamp>/` and prints a report: activity types found, checks for strength sets, run elevation, ski touring, sleep and HRV, failed calls, and an estimate of how long a 24-month backfill takes.

Phase 0 is done when two runs in a row log in with saved tokens and all checks pass. `data/` is in `.gitignore` because it holds tokens and personal data.
