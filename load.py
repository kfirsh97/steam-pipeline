"""Step 2 of the pipeline: load the raw files from the data branch into BigQuery.

    python load.py --data store --project still-sight-513620-v4

Reads every run file under <data>/raw/ (a clone of the data branch) and loads four tables into the `raw` dataset:

    raw.players     one row per game per hourly run: the player count as Steam answered it
    raw.top_games   one row per game per day: the tracked top-100 list (Steam's chart; SteamSpy's before 2026-11-05)
    raw.store       one row per game per day: the store's answer (price, discount, genres) as JSON text
    raw.failures    one row per game that failed in any run, and why

Rules:
- Raw stays raw: values are loaded as they arrived; cleaning is the next step's job (dbt). Nested answers are kept
  as JSON text, so nothing is lost if Steam adds a field.
- Every run rebuilds each table from all the files (WRITE_TRUNCATE), so a re-run gives the same tables and never
  adds duplicates. The files on the data branch are the source of truth; the tables can always be rebuilt from them.
- Each row says which file it came from, so any number in the warehouse can be traced back to one run.
- Each table is replaced in one load job, which BigQuery applies all at once: a failed load leaves yesterday's
  table as it was, never half a table.

Credentials: Application Default Credentials (`gcloud auth application-default login`), never a key file in the repo.
"""

import argparse
import json
import sys
from pathlib import Path

DATASET = "raw"
LOCATION = "US"  # the BigQuery sandbox's default location

# Column name, type, mode. REQUIRED columns make a broken file fail the load instead of loading empty values.
SCHEMAS = {
    "players": [
        ("appid", "INTEGER", "REQUIRED"),
        ("player_count", "INTEGER", "REQUIRED"),
        ("suspicious", "BOOLEAN", "REQUIRED"),
        ("collected_at", "TIMESTAMP", "REQUIRED"),
        ("run_started_at", "TIMESTAMP", "REQUIRED"),
        ("source_file", "STRING", "REQUIRED"),
    ],
    "top_games": [
        ("collected_on", "DATE", "REQUIRED"),
        ("rank", "INTEGER", "REQUIRED"),
        ("appid", "INTEGER", "REQUIRED"),
        ("name", "STRING", "NULLABLE"),
        ("answer", "STRING", "REQUIRED"),
        ("source_file", "STRING", "REQUIRED"),
    ],
    "store": [
        ("appid", "INTEGER", "REQUIRED"),
        ("collected_at", "TIMESTAMP", "REQUIRED"),
        ("run_started_at", "TIMESTAMP", "REQUIRED"),
        ("answer", "STRING", "REQUIRED"),
        ("source_file", "STRING", "REQUIRED"),
    ],
    "failures": [
        ("job", "STRING", "REQUIRED"),
        ("appid", "INTEGER", "REQUIRED"),
        ("error", "STRING", "NULLABLE"),
        ("run_started_at", "TIMESTAMP", "REQUIRED"),
        ("source_file", "STRING", "REQUIRED"),
    ],
}


def _files(data, folder, pattern):
    return sorted((Path(data) / "raw" / folder).glob(pattern))


def _name(path, data):
    return path.relative_to(data).as_posix()


def read_rows(data):
    """{table: [row, ...]} built from every raw file under data/raw/."""
    data = Path(data)
    rows = {table: [] for table in SCHEMAS}
    for path in _files(data, "players", "date=*/hour=*.json"):
        run = json.loads(path.read_text())
        for r in run["records"]:
            rows["players"].append({"appid": r["appid"], "player_count": r["answer"], "suspicious": r["suspicious"],
                                    "collected_at": r["collected_at"], "run_started_at": run["started_at"],
                                    "source_file": _name(path, data)})
        rows["failures"] += _failures("players", run, path, data)
    for path in _files(data, "top_games", "date=*/top_games.json"):
        run = json.loads(path.read_text())
        day = path.parent.name.removeprefix("date=")
        for rank, game in enumerate(run["games"], 1):
            rows["top_games"].append({"collected_on": day, "rank": rank, "appid": game["appid"],
                                      "name": game.get("name"), "answer": json.dumps(game, ensure_ascii=False),
                                      "source_file": _name(path, data)})
    for path in _files(data, "store", "date=*/store.json"):
        run = json.loads(path.read_text())
        for r in run["records"]:
            rows["store"].append({"appid": r["appid"], "collected_at": r["collected_at"],
                                  "run_started_at": run["started_at"],
                                  "answer": json.dumps(r["answer"], ensure_ascii=False),
                                  "source_file": _name(path, data)})
        rows["failures"] += _failures("store", run, path, data)
    return rows


def _failures(job, run, path, data):
    return [{"job": job, "appid": f["appid"], "error": f.get("error"), "run_started_at": run["started_at"],
             "source_file": _name(path, data)} for f in run.get("failures", [])]


def load(rows, project, client=None):
    """Replace each table in project.raw with its rows, one load job per table. Returns {table: row count}."""
    from google.cloud import bigquery

    client = client or bigquery.Client(project=project, location=LOCATION)
    dataset = bigquery.Dataset(f"{project}.{DATASET}")
    dataset.location = LOCATION
    client.create_dataset(dataset, exists_ok=True)
    counts = {}
    for table, table_rows in rows.items():
        config = bigquery.LoadJobConfig(
            schema=[bigquery.SchemaField(name, kind, mode=mode) for name, kind, mode in SCHEMAS[table]],
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )
        job = client.load_table_from_json(table_rows, f"{project}.{DATASET}.{table}", job_config=config)
        job.result()  # waits; raises if BigQuery rejected the load
        counts[table] = len(table_rows)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Load the raw Steam files into BigQuery.")
    parser.add_argument("--data", default="store", help="a clone of the data branch (holds raw/)")
    parser.add_argument("--project", required=True, help="the Google Cloud project ID")
    args = parser.parse_args(argv)
    if not (Path(args.data) / "raw").is_dir():
        print(f"no raw/ folder in {args.data}: clone the data branch there first", file=sys.stderr)
        return 1
    rows = read_rows(args.data)
    if not rows["players"]:
        print("no player files found: nothing to load", file=sys.stderr)
        return 1
    try:
        counts = load(rows, args.project)
    except Exception as error:
        print(f"load failed: {error}", file=sys.stderr)
        return 1
    for table, count in counts.items():
        print(f"{args.project}.{DATASET}.{table}: {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
