# steam-pipeline

Daily data pipeline on Steam games: collects player counts, prices and discounts, loads them to BigQuery, models
them with dbt and orchestrates with Airflow to measure how sales affect players.

**Status:** steps 1-3 built: collection runs every hour, loading to BigQuery and dbt models run on demand. Each run's raw data is saved on the
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
4. Orchestrate loading and modelling with Airflow in Docker, including backfills
5. A dashboard, and the warehouse connected to [RowAsk](https://github.com/kfirsh97/rowask)
6. The analysis: do discounts bring players, and for how long?
