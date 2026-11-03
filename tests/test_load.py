"""Tests for load.py: rows built from run files exactly as collect.py writes them, and loads with a fake client."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import load  # noqa: E402
from test_collect import fake_sources, no_waiting  # noqa: E402,F401
import collect  # noqa: E402


def collected(monkeypatch, tmp_path):
    fake_sources(monkeypatch, top={"730": {"name": "Counter-Strike: Global Offensive", "ccu": 1}, "440": {}, "1": {}},
                 store={730: {"name": "Counter-Strike 2", "is_free": True}, 440: {"name": "Team Fortress 2"}},
                 players={730: 0, 440: 80_000})
    collect.main(["daily", "--out", str(tmp_path)])
    collect.main(["players", "--out", str(tmp_path)])
    return tmp_path


def test_rows_from_real_run_files(monkeypatch, tmp_path):
    rows = load.read_rows(collected(monkeypatch, tmp_path))
    assert [(r["appid"], r["player_count"], r["suspicious"]) for r in rows["players"]] == [(730, 0, True),
                                                                                         (440, 80_000, False)]
    assert [(r["rank"], r["appid"], r["name"]) for r in rows["top_games"]][:2] == [
        (1, 730, "Counter-Strike: Global Offensive"), (2, 440, None)]
    assert json.loads(rows["store"][0]["answer"])["name"] == "Counter-Strike 2"
    assert {(r["job"], r["appid"]) for r in rows["failures"]} == {("store", 1), ("players", 1)}
    assert rows["players"][0]["source_file"].startswith("raw/players/date=")
    for table, table_rows in rows.items():                      # every REQUIRED column is filled
        required = [name for name, _, mode in load.SCHEMAS[table] if mode == "REQUIRED"]
        assert all(r.get(c) is not None for r in table_rows for c in required), table


class FakeJob:
    def result(self):
        return self


class FakeClient:
    def __init__(self):
        self.loads = []

    def create_dataset(self, dataset, exists_ok):
        self.dataset = dataset.dataset_id

    def load_table_from_json(self, rows, table, job_config):
        self.loads.append((table, len(rows), job_config.write_disposition))
        return FakeJob()


def test_every_table_is_replaced_not_appended(monkeypatch, tmp_path):
    client = FakeClient()
    counts = load.load(load.read_rows(collected(monkeypatch, tmp_path)), "proj", client)
    assert client.dataset == "raw" and counts == {"players": 2, "top_games": 3, "store": 2, "failures": 2}
    assert {t for t, _, _ in client.loads} == {f"proj.raw.{t}" for t in load.SCHEMAS}
    assert {mode for _, _, mode in client.loads} == {"WRITE_TRUNCATE"}


def test_no_data_folder_is_a_clear_error(tmp_path, capsys):
    assert load.main(["--data", str(tmp_path), "--project", "p"]) == 1
    assert "clone the data branch" in capsys.readouterr().err
