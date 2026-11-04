# steam-pipeline

Daily data pipeline on Steam games: collects player counts, prices and discounts, loads them to BigQuery, models
them with dbt and orchestrates with Airflow to measure how sales affect players.

**Status:** steps 1-5 built: collection runs every hour on GitHub; loading and dbt run every morning in Airflow;
the dashboard updates itself.

**[Live dashboard](https://datastudio.google.com/reporting/3558ee11-58dd-4977-890f-38206f217126)** - games tracked, players over time, prices and discounts, and how much of each day was actually collected. Each run's raw data is saved on the
[`data` branch](../../tree/data).

## Step 1: collection

| Job | When | What it saves |
|---|---|---|
| `python collect.py players` | every hour | how many people play each of the 100 tracked games right now |
| `python collect.py daily` | every day | SteamSpy's top-100 list, and each game's price, discount, genres and release date |

Sources, all public and free: [SteamSpy](https://steamspy.com) (which games to track: the 100 most played in the
last two weeks), the [Steam Web API](https://partner.steamgames.com/doc/webapi/ISteamUserStats) (current players)
and the Steam store (prices).

The rules the collector follows:

- **Nothing collected today can be collected later**, so one failed game doesn't stop the others. Failures are
  saved in the same file, and the run fails (red, with an email from GitHub) only if more than 20% of the games
  failed.
- **Retries with a growing wait** (1s, 2s, 4s) on timeouts, 429 and 5xx; a 404 is not retried.
- **Safe to run twice**: a file is named by the UTC hour or day it holds (`raw/players/date=2026-11-03/hour=12.json`),
  so a re-run replaces it. It is written to a temporary file and renamed, so a crash never leaves half a file.
- **A zero is suspicious, not dropped**: on 2026-11-03 Steam answered "success, 0 players" for Counter-Strike 2 for
  about two hours, while it had close to a million. Such counts are kept and marked `"suspicious": true`, for the
  cleaning step to decide.

GitHub Actions runs both jobs ([`.github/workflows/`](.github/workflows)) and commits each run to the `data`
branch, so the data never mixes with the code. Tests run on every push.

**The scheduler was the weak point.** In the first 16 hours GitHub's own `schedule` started the hourly job 3
times and the daily job not at all - it is best-effort and skips runs when busy. Now an outside scheduler
([cron-job.org](https://cron-job.org)) starts both jobs on time through GitHub's `workflow_dispatch` API, with a
fine-grained token that can only run this repo's workflows. GitHub's schedule stays as a backup: two runs in the
same hour write the same file. Coverage is measured, not assumed (`collection_coverage` below).

## Step 2: loading to BigQuery

`load.py` reads every run file from a clone of the `data` branch and loads four tables into the `raw` dataset:
`players` (one row per game per hour), `top_games` (the daily top-100 with ranks), `store` (the store's answer as
JSON text) and `failures` (every game that failed, and why).

- **Raw stays raw**: values are loaded as they arrived; nested answers are kept as JSON text for dbt to unpack.
- **Rebuilt every run** (`WRITE_TRUNCATE`): a re-run gives the same tables, never duplicates. The files are the
  source of truth, so the tables can always be rebuilt. This also suits the BigQuery sandbox, which deletes
  tables and partitions after 60 days.
- **Traceable**: every row names the file it came from.
- **No key in the repo**: it uses Application Default Credentials (`gcloud auth application-default login`).

```bash
git clone --branch data --single-branch https://github.com/kfirsh97/steam-pipeline.git store
python load.py --data store --project <your-project-id>
```

## Step 3: dbt models

[`warehouse/`](warehouse) turns the raw tables into tables ready for analysis, in two layers:

| Model | One row per | What it adds |
|---|---|---|
| `staging.stg_players` | game per UTC hour | the hour as a timestamp; a hour collected twice keeps the later answer |
| `staging.stg_store` | game per day | the store's JSON unpacked: price and discount in dollars, genres, release date |
| `staging.stg_top_games` | game per day | rank, SteamSpy's owner range as a number, reviews |
| `marts.dim_games` | game | latest store details, and when it was in the top 100 |
| `marts.fct_game_daily` | game per day | peak and average players without the suspicious zeros, price, discount, on sale, rank |
| `marts.collection_coverage` | day | hourly runs captured vs expected, store runs, failures |

Data tests run with every build: unique keys at each table's grain, no empty keys, player counts and discounts
in range, every daily row's game in `dim_games`. Two generic tests are written here
([`warehouse/tests/generic/`](warehouse/tests/generic)): `between` and `unique_combination`. Coverage under 90%
is a warning, not a failure: a missed hour is lost, but the rest of the day is good data.

```bash
cd warehouse
export GCP_PROJECT=<your-project-id>
dbt build --profiles-dir .
```

## Step 4: orchestration with Airflow

[`orchestration/`](orchestration) runs Airflow in Docker on my computer. One DAG,
[`steam_pipeline`](orchestration/dags/steam_pipeline.py), runs every morning at 04:30 UTC for the UTC day that
just ended:

```
pull_raw_files  ->  check_day_collected  ->  load_raw  ->  dbt_build
```

- **Check before load**: `check_day_collected` fails if the day's hourly files or store file haven't arrived, and
  Airflow retries it twice, 20 minutes apart - a late collector doesn't produce an empty day. A day with fewer
  than 20 of 24 hours is loaded, and the missing hours are named in the log.
- **Catch-up**: the computer isn't always on. `catchup=True` makes Airflow create one run per missed day when it
  comes back, oldest first, one at a time.
- **Split by what each tool does well**: collection must never miss an hour, so it runs on GitHub with an outside
  scheduler; loading and modelling can wait for the computer, so they run in Airflow, which gives retries,
  dependencies and catch-up. This also keeps it free: a managed Airflow costs hundreds of dollars a month.
- **Two Python environments in one image**: Airflow's, and a separate one for `load.py` and dbt, so their
  dependencies never clash.
- **No secrets in the image**: the Google sign-in is mounted read-only from the computer; the UI listens on
  localhost only.

```bash
cd orchestration
cp .env.example .env            # then put your project ID in .env
docker compose up -d --build    # first build takes a few minutes
open http://localhost:8080
```

## Step 5: the dashboard

A [Data Studio report](https://datastudio.google.com/reporting/3558ee11-58dd-4977-890f-38206f217126) on
`marts.dashboard_game_daily` (one flat row per game per day, built by dbt for the dashboard) and
`marts.collection_coverage`. It reads BigQuery directly, so it shows the latest build without any export.

- Games tracked and games on sale, players over time for the top 10, and a table of every game's peak, lowest
  price and largest discount in the chosen dates - each aggregated with MAX or MIN, never summed across days.
- Filters for dates, genres and on sale.
- **Data coverage**: the share of hourly runs captured each day, next to the numbers it qualifies. A day with low
  coverage has a lower peak only because it wasn't measured, and the dashboard says so.

## Run it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
python collect.py players --out store
```

## Next steps

1. ~~Collection~~
2. ~~Load the raw files into BigQuery~~
3. ~~Clean and model them with dbt, with data tests~~
4. ~~Orchestrate loading and modelling with Airflow in Docker, with catch-up~~
5. ~~A dashboard~~; next, the warehouse connected to [RowAsk](https://github.com/kfirsh97/rowask)
6. The analysis: do discounts bring players, and for how long?
