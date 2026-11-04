"""Copy the marts tables from BigQuery into one SQLite file - a snapshot anyone can query with no Google account.

    python export_sqlite.py --project still-sight-513620-v4 --out steam.sqlite

Used for RowAsk's public demo (github.com/kfirsh97/rowask): visitors ask questions about the Steam games without
any access to the BigQuery project, and the queries cost nothing. The snapshot is only as fresh as its last export.

Rules:
- Every table in the marts dataset is copied with all its columns, so the snapshot never drifts from dbt's models.
- Types SQLite doesn't have are written the way a query would want them: DATE/TIMESTAMP as ISO text (sorts and
  compares correctly), BOOLEAN as 0/1, an ARRAY as one comma-separated text ("Action, Free To Play").
- The file is built under a temporary name and moved into place at the end, so a failed export never leaves half
  a database where the old one was.
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

DATASET = "marts"
LOCATION = "US"
SQLITE_TYPES = {"INTEGER": "INTEGER", "INT64": "INTEGER", "FLOAT": "REAL", "FLOAT64": "REAL", "NUMERIC": "REAL",
                "BIGNUMERIC": "REAL", "BOOLEAN": "INTEGER", "BOOL": "INTEGER"}


def sqlite_value(value, field):
    """One BigQuery value as SQLite stores it."""
    if value is None:
        return None
    if field.mode == "REPEATED":
        return ", ".join(str(v) for v in value)
    if field.field_type in ("BOOLEAN", "BOOL"):
        return int(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def column_type(field):
    return "TEXT" if field.mode == "REPEATED" else SQLITE_TYPES.get(field.field_type, "TEXT")


def export(client, project, out):
    """Write every table of project.marts into a new SQLite file at out. Returns {table: row count}."""
    out = Path(out)
    tmp = out.with_name(out.name + ".tmp")
    tmp.unlink(missing_ok=True)
    counts = {}
    con = sqlite3.connect(tmp)
    try:
        for item in sorted(client.list_tables(f"{project}.{DATASET}"), key=lambda t: t.table_id):
            table = client.get_table(item.reference)
            fields = table.schema
            cols = ", ".join(f'"{f.name}" {column_type(f)}' for f in fields)
            con.execute(f'CREATE TABLE "{table.table_id}" ({cols})')
            rows = [tuple(sqlite_value(row[f.name], f) for f in fields) for row in client.list_rows(table)]
            marks = ", ".join("?" for _ in fields)
            con.executemany(f'INSERT INTO "{table.table_id}" VALUES ({marks})', rows)
            counts[table.table_id] = len(rows)
        con.commit()
    finally:
        con.close()
    if not counts:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"no tables in {project}.{DATASET}: run dbt build first")
    os.replace(tmp, out)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Copy the BigQuery marts into one SQLite file.")
    parser.add_argument("--project", required=True, help="the Google Cloud project ID")
    parser.add_argument("--out", default="steam.sqlite", help="the SQLite file to write")
    args = parser.parse_args(argv)
    from google.cloud import bigquery
    try:
        counts = export(bigquery.Client(project=args.project, location=LOCATION), args.project, args.out)
    except Exception as error:
        print(f"export failed: {error}", file=sys.stderr)
        return 1
    for table, count in counts.items():
        print(f"{table}: {count} rows")
    print(f"wrote {args.out} ({Path(args.out).stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
