import datetime as dt
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_sqlite  # noqa: E402


def field(name, kind, mode="NULLABLE"):
    return NS(name=name, field_type=kind, mode=mode)


class FakeClient:
    """Two marts tables, with the BigQuery types the real ones use."""
    tables = {
        "dim_games": ([field("appid", "INTEGER"), field("name", "STRING"), field("genres", "STRING", "REPEATED"),
                       field("is_free", "BOOLEAN"), field("release_date", "DATE")],
                      [{"appid": 730, "name": "Counter-Strike 2", "genres": ["Action", "Free To Play"],
                        "is_free": True, "release_date": dt.date(2012, 8, 21)}]),
        "collection_coverage": ([field("collected_on", "DATE"), field("coverage_pct", "FLOAT")],
                                [{"collected_on": dt.date(2026, 11, 4), "coverage_pct": 62.5},
                                 {"collected_on": dt.date(2026, 11, 3), "coverage_pct": None}]),
    }

    def list_tables(self, dataset):
        return [NS(table_id=t, reference=t) for t in self.tables]

    def get_table(self, ref):
        return NS(table_id=ref, schema=self.tables[ref][0])

    def list_rows(self, table):
        return self.tables[table.table_id][1]


def test_export_copies_every_table_with_sqlite_types(tmp_path):
    out = tmp_path / "steam.sqlite"
    counts = export_sqlite.export(FakeClient(), "p", out)
    assert counts == {"collection_coverage": 2, "dim_games": 1}
    con = sqlite3.connect(out)
    assert con.execute("select appid, name, genres, is_free, release_date from dim_games").fetchone() == \
        (730, "Counter-Strike 2", "Action, Free To Play", 1, "2012-08-21")
    assert con.execute("select max(collected_on), count(coverage_pct) from collection_coverage").fetchone() == \
        ("2026-11-04", 1)
    assert not (tmp_path / "steam.sqlite.tmp").exists()


def test_a_failed_export_keeps_the_old_file(tmp_path):
    out = tmp_path / "steam.sqlite"
    out.write_text("old")

    class Broken(FakeClient):
        def list_rows(self, table):
            raise RuntimeError("network down")

    try:
        export_sqlite.export(Broken(), "p", out)
    except RuntimeError:
        pass
    assert out.read_text() == "old"
