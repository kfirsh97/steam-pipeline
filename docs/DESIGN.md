# Design: steam-pipeline

What the pipeline does is in the [README](../README.md). This page is about **why it is built this way**: the
decisions, what each one traded away, and what to do when something breaks.

## Goal

A pipeline that runs by itself and answers one business question: **does a discount bring players to a game, how
many, and for how long?** It collects hourly player counts and daily prices for Steam's 100 most played games,
loads them into BigQuery, models and tests them with dbt, orchestrates with Airflow, and shows the result on a
public dashboard.

## Architecture

```
                 always on (cloud)                          |  my computer        |  Google Cloud
cron-job.org --> GitHub Actions: collect.py --> data branch --> Airflow in Docker --> BigQuery raw --> dbt --> Data Studio
   (on time)     (Steam Web API, store, charts)    (one file      (pull, check, load,                 (staging,
                                                    per run)        build, catch up)                  marts, tests)
```

Collection runs in the cloud because an hour that isn't collected is lost for good. Loading and modelling run on
my computer because they can wait: Airflow catches up on the days the computer was off.

## Decisions and trade-offs

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| Where collection runs | GitHub Actions, started by an outside scheduler | Airflow on my computer | Data not collected on time is gone; the computer isn't always on |
| What starts the hourly job | cron-job.org calling `workflow_dispatch` | GitHub's own `schedule` | In the first 16 hours GitHub's schedule ran the hourly job 3 times and the daily job never; it's best-effort and skips runs when busy |
| Where loading and dbt run | Airflow 3.3 in Docker on my computer | Managed Airflow (Cloud Composer, MWAA) | Managed Airflow costs hundreds of dollars a month; this work can wait, and catch-up covers the gaps |
| Where raw files live | A `data` branch in the repo | A cloud bucket | Free, public, full history; the data is a few MB a day |
| How tables are loaded | Each table rebuilt from all files every run (`WRITE_TRUNCATE`) | Loading one day into a partition | The BigQuery sandbox deletes partitions after 60 days, and the data is small enough to rebuild in seconds. The files are the source of truth |
| Which games to track | Steam's own most-played chart, SteamSpy as fallback | SteamSpy's top 100 only | SteamSpy's answer was identical for three days, kept old names, and had no Dota 2; a source that stops updating is checked by comparing days, not assumed fresh |
| BigQuery account | The free sandbox, no credit card | A billing account | Its limits (60-day expiry, no DML) don't matter when every table is rebuilt from files |
| Airflow schedule | `CronDataIntervalTimetable` | A plain cron string | In Airflow 3 a plain cron string starts and ends the interval at the run time; an interval timetable makes each run's `data_interval_start` the UTC day it checks |
| Python environments | Airflow's, plus a separate virtualenv for `load.py` and dbt in the same image | One environment | Airflow's and dbt's dependency pins clash |
| Data tests | Two generic tests written here (`between`, `unique_combination`) | A test package (dbt-utils) | No extra dependency, and each test is a few readable lines |
| dbt version | 1.12 | dbt 2 | Most company projects still run v1 |
| RowAsk's public demo | A SQLite snapshot of the marts (`export_sqlite.py`) | Connecting the demo to BigQuery | Strangers' questions would run on my project, and the cloud host would need a Google key; the snapshot exposes no access to the warehouse. (The embedded Data Studio report does read BigQuery live, with my credentials, as the public dashboard always has - a few MB a day, well inside the free query quota) |
| Dashboard | Data Studio, reading BigQuery live | Tableau Public | Tableau Public can't connect to BigQuery; it would need a manual export |

## Data quality rules

- **One failed game doesn't stop the others**: failures are saved with the run, and the run fails only above 20%.
- **Retries** with 1s, 2s, 4s waits on timeouts, 429 and 5xx; never on 404.
- **Safe to re-run** at every step: files are named by the UTC hour or day, tables are replaced, never appended.
  A second run in the same hour keeps whichever file has more real counts; a second daily run adds to the first.
- **Only finished days in the marts**: the current UTC day appears once it is over, so a partial day's low peak is
  never read as a real one. `full_day` marks game-days with at least 20 usable hours.
- **Unknown is not false**: `on_sale` is NULL when there was no store answer that day, not "full price".
- **A list that fails doesn't switch tracking**: if Steam's chart fails, the last saved list is kept and the run is
  marked failed; SteamSpy is used only with no saved list.
- **A zero is suspicious, not dropped**: on 2026-11-03 Steam answered "success, 0 players" for Counter-Strike 2 for
  about two hours while it had close to a million. Zeros are kept and marked; the daily facts leave them out.
- **Coverage is measured, not assumed**: `collection_coverage` counts the hours captured on every finished day (a
  day with no run is 0%, not missing), and a day under 90% is a dbt warning and a bar on the dashboard.
- **Dashboard numbers are never summed across days**: peak and discount use MAX, price uses MIN.

## Security

| What | How it is protected |
|---|---|
| BigQuery access | The Google sign-in stays on my computer and is mounted into the container read-only. No key file in the repo or the image |
| The scheduler's token | A fine-grained GitHub token: this repo only, Actions read and write only. Stored only in cron-job.org; expires 2027-11-03 |
| Airflow UI | Listens on localhost only, so it has no login screen |
| Airflow's database | Reachable only from the Airflow container; no port opened to the computer |
| Project ID | Not a secret (it grants nothing without a sign-in); it appears in usage examples. Airflow reads it from `orchestration/.env` |
| The demo's push token | A fine-grained GitHub token: the rowask repo only, Contents read and write only. In `orchestration/.env`; given to git as a header, never in a URL or a log |
| Dashboard | View-only; viewers get no access to the warehouse |

## Known limitations

- The first two days are partial: 2 of 24 hours on 2026-11-03, most of the morning missing on 2026-11-04.
- Only players connected to Steam are counted.
- The tracked list follows Steam's top 100, so a game that drops out stops being collected.
- **2026-11-05 is a break in the series**: the list switched from SteamSpy's to Steam's chart that day and 56 games
  changed, so that day is partial for them, and set-wide averages and ranks aren't comparable across it.
- One price reading per day (at 00:15 UTC): a sale that starts later that day shows from the next day.
- On BigQuery, RowAsk's read-only validator is the only guard, and it runs with my own sign-in. The next step is a
  viewer-only service account limited to the marts dataset.
- No alert yet when the DAG fails or the warehouse is stale: the Airflow UI and dbt's warnings show it.
- The scheduler's token expires on 2027-11-03; after that only GitHub's unreliable schedule is left.
- GitHub disables scheduled workflows after 60 days without a commit; the outside scheduler isn't affected.

## Runbook

| Symptom | What to do |
|---|---|
| A collection run is red on GitHub | Open the red step and read the first failure. What was collected is already saved |
| cron-job.org shows 401 | The token expired or was revoked: make a new one and replace it in both jobs |
| `check_day_collected` failed in Airflow | That day's files didn't arrive: check the collection runs on GitHub |
| `dbt_build` failed | Find the failing test in the log, run its compiled SQL in BigQuery to see the rows |
| The computer was off for days | Nothing: Airflow runs every missed day when it comes back |
| `refresh_demo` failed | Read its log: a 401/403 means the token expired or lacks Contents write. The warehouse is fine either way |
| After a restart Airflow is down | `cd orchestration && docker compose up -d` |

## Next

1. The sale analysis, after two to three weeks of data: each sale's week before, during and after.
2. An email when coverage drops, not only a warning in the log.
3. With a billing account: partitioned tables and loading only the new day.
