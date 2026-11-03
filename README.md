# steam-pipeline

Daily data pipeline on Steam games: collects player counts, prices and discounts, loads them to BigQuery, models
them with dbt and orchestrates with Airflow to measure how sales affect players.

**Status:** step 1 of 6, collection, is running. Each run's raw data is saved on the
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

## Run it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
python collect.py players --out store
```

## Next steps

1. ~~Collection~~
2. Load the raw files into BigQuery, partitioned by day
3. Clean and model them with dbt, with data tests
4. Orchestrate loading and modelling with Airflow in Docker, including backfills
5. A dashboard, and the warehouse connected to [RowAsk](https://github.com/kfirsh97/rowask)
6. The analysis: do discounts bring players, and for how long?
