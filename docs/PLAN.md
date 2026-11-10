# Garmin coach plan

A self-hosted training coach. It syncs Garmin data to a Raspberry Pi, computes training metrics locally, and lets an AI coach plan and review training through a web UI reached over VPN.

## Goals

- Plan and track training toward a goal race, for example a mountain marathon.
- Give feedback on every session: running, strength, cross-country skiing, alpine skiing, ski touring and bike commuting.
- Keep goals, plans and history as structured data that the coach reads and proposes changes to.
- Base advice on a curated library of research findings that I approve, with sources the coach cites.

## Constraints

- Hardware: Raspberry Pi 4, 4 GB RAM, deployed in the last phase. Until then the app runs in Docker on the Debian development machine. No local LLM. The model runs through the Claude API.
- Scheduled jobs (sync, morning check-in, weekly review) only run while the host is on. Before the Pi, that means the Debian machine.
- Two users in one household, accessed over VPN. One instance serves both with profiles: each profile has its own database and Garmin tokens under `data/profiles/<name>/`, and the research library is shared in `data/research.db`. There is no login; the app asks who is training. The API budget is shared.
- The API budget is 5 to 10 dollars a month.
- Garmin has no official personal API. The sync depends on `python-garminconnect`, which broke in March 2026 when Garmin changed its login. The adapter must be isolated so a library swap or FIT file import can replace it.
- The SD card wears out under database writes. Data lives on a USB SSD.

## Architecture

```
                 +-------------------- Raspberry Pi (Docker) ---------------------+
 Garmin Connect  |                                                                |
 <---------------+-- sync worker --> raw_* tables --> normalizer --> core tables  |
                 |   (scheduled)                                        |         |
 PubMed /        |                                              metrics engine    |
 Europe PMC <----+-- evidence job --> evidence (pending/approved)       |         |
                 |                          |                           v         |
                 |                          +-------> coach (Claude API + tools)  |
                 |                                             |                  |
                 |   FastAPI  <-- REST + SSE -->  React SPA (static files)        |
                 +----------------------------------------------------------------+
                                  ^
                                  | VPN
                               phone / laptop
```

There is one backend process: FastAPI plus APScheduler for the sync, metrics and evidence jobs. A single process is enough for one user and keeps SQLite free of cross-process write contention.

## Tech stack

| Part | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, APScheduler |
| Tooling | uv, ruff, pytest, mypy |
| Database | SQLite in WAL mode, FTS5 for evidence search |
| Garmin | `python-garminconnect` behind a `GarminSource` interface, `fitparse` for the FIT fallback |
| LLM | `anthropic` Python SDK |
| Frontend | React, Vite, TypeScript, Tailwind, shadcn/ui, TanStack Query, ECharts |
| Deploy | Docker Compose, arm64 image built with buildx on the laptop |
| Notifications | ntfy (self-hosted or ntfy.sh) |

## Data model

Raw data and derived data are kept apart. Garmin responses are stored as JSON before parsing, so a parser fix can rebuild the core tables without fetching again.

Raw tables:

- `raw_activity(garmin_id, endpoint, fetched_at, body)`, where endpoint is summary, activity, details, splits, hr_zones or exercise_sets.
- `raw_daily(date, kind, fetched_at, body)`, where kind is stats, sleep, hrv, readiness, training_status or body_composition.
- `body` is gzip-compressed JSON. The activity details response averages about 1 MB per activity and a sleep response about 146 KB per day. Gzip shrinks both about 8 times, which puts 24 months of raw data at roughly 70 MB instead of 566 MB.

Core tables:

- `activity`: id, start time, sport, sub-sport, duration, moving time, distance, elevation gain and loss, average and max HR, Garmin training load, aerobic and anaerobic training effect, a commute flag and the raw activity id.
- `activity_lap`: per-lap distance, time, elevation, HR, pace and power.
- `activity_zone_time`: seconds per HR zone (and power zone where present).
- `strength_set`: activity, order, exercise category, exercise name, reps, weight, duration, set type (active or rest).
- `strength_set_override`: the corrected values for a set. It survives re-syncs, and reads use the override when it exists.
- `exercise_muscle_map`: Garmin exercise category to primary and secondary muscle groups.
- `daily_wellness`: date, sleep duration and stages, sleep score, nightly HRV, HRV status, resting HR, body battery, stress, readiness, training status.
- `body_composition`: date, weight, body fat, muscle mass.

Metric tables, recomputed after each sync:

- `daily_load`: date, load per sport group, acute (7-day EWMA), chronic (42-day EWMA).
- `weekly_summary`: week, time and distance per sport, vertical gain, longest run, time in each zone, hard sets per muscle group.

Coaching tables:

- `athlete_profile`: birth year, sex, height, max and resting HR, HR zone model, injury history, available training days, equipment.
- `goal`: type (race, strength, habit), title, target date, target value, race details (distance, elevation gain, terrain, cutoffs), priority, status.
- `plan`, `planned_session`: the training plan. A session has sport, date, type (easy, long, intervals, hills, strength, rest), targets (duration, distance, vertical, zone, exercises) and notes. Weeks come from the dates, so there is no `plan_week` table.
- `session_match`: links a planned session to the activity that fulfilled it, with a compliance score.
- `plan_change_proposal`: changes the coach proposes. Nothing reaches the plan until I accept it.
- `coach_note`: short facts the coach saves for later ("prefers long runs on Saturdays, 2026-10-20").
- `conversation`, `message`: chat threads, with the full API content blocks stored.
- `evidence`: see the evidence library section.
- `api_usage`: tokens and cost per call.

## Sync

- Every 60 minutes between 05:00 and 23:00, and on demand from the UI.
- Pull activities since the last sync, then the activity details. Pull the daily wellness data for the last 3 days, because Garmin fills sleep and HRV in late.
- The first backfill fetches 24 months at a low rate (one request every 2 seconds) so it doesn't trip Garmin's rate limit. For a history of about 600 activities that is about 6,200 calls and 4 hours. It can resume after an interruption.
- A login with credentials took 55 seconds in Phase 0. A login with saved tokens took 0.5 seconds. The sync always uses saved tokens and only asks for credentials when Garmin rejects them.
- Garmin tokens are stored in the data volume. A failed login raises a visible banner in the UI and an ntfy message.
- An activity is tagged as a commute when it is a bike ride that starts and ends near the saved home and work locations. A manual toggle overrides the tag.

## Metrics

Load across sports:

- The per-activity load is Garmin's training load when present. Otherwise it is Banister TRIMP from HR.
- Acute and chronic load are exponentially weighted averages over 7 and 42 days, shown as trends.
- The acute:chronic ratio is not presented as an injury predictor. Impellizzeri et al. (2020) describe conceptual and statistical problems with it, so the app shows the load trend and big week-to-week jumps instead.

Sport groups:

| Group | Garmin type keys | Counted toward |
|---|---|---|
| Run | `running`, `trail_running`, `treadmill_running`, `ultra_run` | run volume, vertical, endurance load |
| Vertical cross-training | `hiking`, `stair_climbing` | vertical and time on feet, endurance load |
| Ski | `backcountry_skiing`, `skate_skiing_ws`, `cross_country_skiing_ws` | endurance load. Touring ascent also counts toward vertical |
| Commute | outdoor `cycling` tagged as a commute | load, shown as background volume, kept out of plan targets |
| Other cycling | `cycling` not tagged as a commute, `indoor_cycling` | endurance load |
| Other endurance | `elliptical` | endurance load |
| Alpine | `resort_skiing` | low aerobic load, logged as leg-loading days |
| Strength | `strength_training` | hard sets per muscle group, estimated 1RM |
| Other | `bouldering`, `squash`, `paddelball` and any unmapped key | load from HR only |

The mapping is a table in the database, not code. A type key that isn't in the table lands in Other and shows up in settings so I can assign it a group.

Few trail runs are recorded as `trail_running`, so the type key can't tell road from trail. Each run is classified by terrain from its elevation gain per km and the share of laps with steep grades.

Trail running and the goal race:

- Weekly distance, time, vertical gain and descent.
- Grade-adjusted pace, using the Minetti et al. (2002) energy cost of running on slopes.
- Longest run by time and by vertical, and back-to-back long days.
- A rough race-time projection from recent long runs and climbing efficiency (vertical meters per hour at a given HR). The UI labels it as an estimate.

Strength:

- Hard sets per muscle group per week, from the corrected sets.
- Estimated 1RM with the Epley formula for main lifts, tracked over time.
- Single-leg and eccentric work (step-downs, split squats, Nordics) tracked separately, since they matter for downhill running.

Recovery:

- Nightly HRV against the athlete's own baseline: a 7-day rolling mean of ln(rMSSD) compared with the 60-day mean plus or minus a smallest worthwhile change of 0.5 SD (Plews et al. 2013).
- Resting HR trend, sleep duration and consistency.
- Garmin readiness and training status shown as given, labeled as Garmin's scores.

## Coach

Models (configurable in settings):

- Chat: `claude-sonnet-5-5` ($2 in, $10 out per million tokens, cache reads $0.20).
- Building or rebuilding a training plan: `claude-opus-5-5` ($4 in, $20 out) at effort `high`. This happens a few times per training block. Refusals use the server-side `fallbacks: "default"` option.
- Proactive messages and background jobs (morning check-in, activity feedback, weekly review, evidence summaries): `claude-haiku-5-5` ($0.10 in, $0.50 out).
- Rough cost per person per month: 40 chat messages at about 5 to 10 cents each (2 to 4 dollars), 65 proactive messages at under 1 cent each, and 2 plan builds at about 1 dollar each. That is 3 to 6 dollars per person, so two people land near the top of the budget. The cap below keeps the total from going over.
- Every call logs its token usage and cost to `api_usage`. The settings page shows the monthly total. At 80% of the instance's budget the UI warns. At 100% every coach call stops until the next month, the proactive messages included.

Agent loop:

- A manual streaming loop. It forwards text deltas to the browser over SSE and sends tool-call events, so the UI can show what the coach is looking up ("reading last 4 weeks of runs").
- Tool inputs are validated against their schemas before running. A failed tool returns `is_error: true` to the model.

Read tools:

- `get_profile`, `get_goals`, `get_plan(range)`
- `list_activities(range, sport)`, `get_activity(id)` with laps, zones and sets
- `get_wellness(range, fields)`, `get_load(range)`, `get_weekly_summary(range)`
- `get_strength_progress(exercise or muscle group, range)`
- `search_evidence(query)`, which returns only approved entries
- `get_notes(query)`

Write tools (each creates a proposal or a record I can see and undo):

- `propose_plan_change(changes, reason)`
- `propose_plan(goal_id, weeks, reason)`
- `save_note(text)`
- `update_goal(goal_id, fields)` (needs my confirmation in the UI)

Prompt and caching:

- The system prompt is fixed text: the coach's role, how to use the tools, a rule to cite evidence by id and DOI, and a rule to say when data is missing instead of guessing.
- Tool definitions come in a fixed order. The system prompt and tools sit before the cache breakpoint, so every turn reads them from the cache.
- Volatile context goes after the breakpoint: today's date, a short snapshot (readiness, this week's plan, the last 3 activities) and the user's message.
- Long threads use server-side compaction. The full content blocks are stored, so compaction blocks survive.

Proactive messages:

- A morning check-in at a set time: readiness, today's planned session and an adjustment if recovery data says so.
- Feedback after each synced activity: compared with the plan and with similar past sessions.
- A Sunday weekly review: plan compliance, load trend and a proposal for next week.
- Each one becomes a message in a "Coach" thread and an ntfy notification.

## Evidence library

Pipeline:

1. A topic watchlist in settings, for example: trail running performance, downhill running and muscle damage, heavy strength training for endurance runners, concurrent training, intensity distribution, HRV-guided training, tapering, carbohydrate intake during ultra races.
2. A weekly job queries the PubMed E-utilities and Europe PMC REST APIs for new reviews, meta-analyses and trials on each topic.
3. Haiku turns each abstract into an entry: claim, population, intervention, outcome, study design, sample size, direction of effect, practical takeaway, limitations and DOI.
4. A grade comes from the study design: meta-analysis or systematic review, randomized trial, observational study, other.
5. New entries wait as `pending`. The review screen shows each entry with a link to the paper, and I approve, edit or reject it.
6. Approved entries are indexed with FTS5. An entry can be marked as disputed by a later entry, and the coach sees both.

Seed papers to pull through the same pipeline, then verify:

- Seiler (2010), training intensity distribution in endurance athletes.
- Rønnestad and Mujika (2014), strength training for running and cycling performance.
- Blagrove et al. (2018), strength training and the physiological factors in distance running.
- Kiviniemi et al. (2007) and Plews et al. (2013), HRV-guided training and monitoring.
- Impellizzeri et al. (2020), problems with the acute:chronic workload ratio.
- Minetti et al. (2002), energy cost of running on slopes.

## Web UI

| Page | Content |
|---|---|
| Today | readiness and HRV status, today's planned session, the latest coach message, sync status |
| Chat | threads, streaming replies, the tool calls the coach made, proposals accepted with one click |
| Plan | calendar of planned and completed sessions, compliance, pending proposals |
| Activity | summary, HR, pace and elevation charts, laps, zones, strength set editor |
| Trends | load, weekly vertical and distance, HRV against baseline, hard sets per muscle group, 1RM |
| Goals | goals with race details and progress |
| Evidence | review queue and approved library |
| Settings | Garmin connection, models and monthly cost, schedules, topics, home and work locations, ntfy |

The layout is mobile-first, since the phone over VPN is the main client. Dark mode is on by default.

## Deployment

- Docker Compose with one `app` service from Phase 1, on the Debian machine. The second user gets a second service with its own data directory and port. A multi-stage build compiles the frontend and copies it into the Python image. Running in Docker from the start keeps the move to the Pi down to an arm64 image build and a data copy.
- Images are built on the laptop with `docker buildx --platform linux/arm64` and loaded on the Pi over SSH, because building the frontend on a Pi 4 is slow.
- The `data/` volume (SQLite, Garmin tokens, backups) is on the USB SSD.
- Secrets: the Anthropic key is saved on the Settings page in `data/research.db`, which only the owner can read, or in a `.env` file outside git. Garmin passwords go straight to Garmin from the setup form or `coach login`, and only the tokens are kept per profile.
- No app login. The VPN is the only access control, and both users may see each other's data.
- A nightly job runs `sqlite3 .backup`, keeps 14 days, and copies the latest backup to the laptop or NAS.
- `/health` reports the last successful sync and the last job runs.

## Repo layout

```
backend/
  src/garmin_coach/
    api/          FastAPI routers
    coach/        agent loop, tools, prompts
    evidence/     PubMed and Europe PMC clients, summarizer
    garmin/       GarminSource interface, garminconnect adapter, FIT import
    metrics/      load, running, strength, recovery
    migrations/   Alembic migrations, shipped inside the package
    models/       SQLAlchemy models
    normalize/    raw JSON to core tables, sport mapping
    jobs/         scheduler and job definitions
    cli.py        the `coach` command
    raw_store.py  gzip JSON in the raw tables
    sync.py       recent sync and resumable backfill
  tests/
frontend/
  src/
docker/
docs/
scripts/
```

## Phases

Each phase ends with a check that shows it works.

**Phase 0: Garmin spike.** Write `scripts/garmin_probe.py`. It logs in, saves tokens, pulls 7 days of activities, details and wellness data, and dumps the raw JSON. Run it on the Debian machine. Done when two runs in a row succeed on saved tokens, and the dump contains a strength activity with sets, a run with elevation data and, from older history, a ski touring activity.

Phase 0 result (27 October 2026): done. Two runs passed, the second on saved tokens, with no failed calls. Findings:

- Strength sets come with Garmin's exercise category and name (for example `SQUAT`/`SQUAT`, `DEADLIFT`/`ROMANIAN_DEADLIFT`), reps and weight. Weight is in grams. Warm-up sets have no reps or weight.
- The activity summary includes `activityTrainingLoad`, so the per-activity load can use Garmin's number directly.
- `ultra_run` is its own type key. The type key list is in the sport groups table above.
- Each API call takes about 0.35 seconds.

**Phase 1: Data foundation.** Schema, migrations, sync worker, normalizer, metrics, backfill, the Today and Trends pages, Docker Compose on the Debian machine. Done when a 24-month backfill completes in Docker on the Debian machine, and weekly distance and vertical for 4 sample weeks match Garmin Connect.

**Phase 2: Coach chat.** Agent loop, read tools, profile and goals pages, threads, cost tracking. Done when "How did my last 4 weeks of running compare to what my goal race needs?" gets an answer built from tool calls and real numbers, and the cost of the turn shows in settings.

Phase 2 result (29 October 2026): done.

- The coach runs on `claude-sonnet-5-5` at effort `low` with 11 read tools and `save_note`. The question above got its answer from `get_running_weeks`, `get_goals` and `get_notes`, and the turn cost $0.02. The second call in the turn read the 3,171-token system prompt and tools from the cache.
- Every message is stored with its full content blocks, and the history is only ever appended to, so thinking blocks stay valid. Requests set `drop_block` for thinking blocks that fail the conversation check, so a later change to the system prompt or the tools doesn't break old threads.
- Each user message starts with a context block (date, last night's recovery, this week so far, active goals) after the cached prefix.
- Not done yet: the login (the server still binds to 127.0.0.1 only, and comes with the Pi in Phase 6), Opus for plan building and Haiku for proactive messages (Phase 3).

**Phase 3: Plans and feedback.** Plan tables, proposals, the calendar, matching sessions to activities, strength set editor, feedback after each activity, morning check-in, weekly review, ntfy. Done when the coach proposes a block toward the race, I accept it, a synced run gets matched with a compliance score, and its feedback arrives on my phone.

Phase 3 result (30 October 2026): built, waiting for the first real plan.

- Plans: `propose_plan` and `propose_changes` create proposals, and the Plan page shows each one with Accept and Reject. A new plan replaces every planned session from its first day on. Plan requests run on `claude-opus-5-5` at effort `high`. A test call cost 2.8 cents, almost all of it the cache write.
- Matching: after each sync, plan change, skip or delete, every planned session in the range is matched to an activity of a fitting sport on the same day, or the day before or after. Compliance is the mean of how close duration, distance and climbing came to their targets, so 2 h done on a 1 h plan scores low too.
- Activity page with stats, HR zones, laps, the planned session it fulfilled, and the strength set editor. Edits are stored as overrides and survive syncs.
- Proactive coach: a morning check-in, feedback on new activities after a sync, and a weekly review, all in a weekly "Coach" thread. Check-ins and feedback use `claude-haiku-5-5`, and the review uses the chat model. The first real check-in cost 0.11 cents. ntfy notifications are off until `NTFY_TOPIC` is set.
- Left for the done check: ask for a block toward the race, accept it, and let a synced run get matched and its feedback reach the phone.

**Phase 4: Evidence library.** Watchlist, fetch job, summarizer, review queue, `search_evidence`. Done when the seed papers are approved and the coach cites one by DOI when asked about strength training for trail running.

Phase 4 result (2 November 2026): built, waiting for your review.

- Six topics with weekly limits: Running 5, and 2 each for strength training, cross-country skiing, ski touring, cycling and commuting, and general training research. That is up to 15 papers a week. Topics, searches and limits can be edited on the Research page.
- PubMed only. Europe PMC is left out because it indexes the same journals, and two sources would mean deduplicating by DOI. The 7 seed papers were found by searching PubMed, and their PubMed ids are stored.
- The first fetch added 22 papers (7 seeds and 15 from topics) for $0.008 in Haiku summaries.
- When PubMed tags a paper only as Review, it is graded as a narrative review, even if the model called it systematic. Haiku had graded Seiler 2010 and Rønnestad 2014 as A.
- On a copy of the database with 4 strength papers approved, the coach answered a question about strength training for trail running with `search_evidence` and cited Llanos-Lagos 2024, Blagrove 2018, Rønnestad 2014 and Prieto-González 2022 by DOI and grade. The turn cost $0.037. The done check passes once you approve the seed papers in your own library.

Feedback round (3 November 2026):

- Planned sessions have steps (warm-up, steady parts, intervals with repeats and recovery, cool-down) and exercises (sets, reps, load, rest). A session opens in a dialog with a step list or an exercise table. `coach structure-sessions` split the 27 old session texts with Haiku for $0.007.
- HR zones follow Uphill Athlete's five zones from LT1 and LT2: zone 1 ends at 90% of LT1, zone 2 at LT1, zone 3 at LT2 and zone 4 at 5% above LT2. Thresholds are stored as dated tests. Each activity keeps seconds per bpm from the raw details, so new zones apply to the whole history at once. Trends shows the zones and weekly time in zone. The activity page shows heart rate drift and pace to HR decoupling after a 15 min warm-up, and can save a steady run as an LT1 test. The coach gets the zones in its context and a `get_zone_time` tool.
- Profiles replace the second instance. The old single-person data moved into `data/profiles/<name>/` and the 22 papers into `data/research.db`. The budget is counted across every profile and the research library.

**Phase 5: Extras.** Push planned workouts to the Garmin watch, FIT file import fallback, nutrition import, race-time projection.

**Phase 6: Raspberry Pi.** Move the app to the Pi when it is available, with a profile for the second user: USB SSD for `data/`, arm64 image built with buildx, Garmin login check from the Pi (copied tokens or a fresh login), nightly backups, VPN access from the phone. Done when the Pi has run the scheduled sync and morning check-in for 7 days in a row without errors, and the app works from the phone over VPN.

## Open questions

- ntfy.sh or a self-hosted ntfy.
- Which days of the week are available for long runs and strength. Asked again before Phase 3.
