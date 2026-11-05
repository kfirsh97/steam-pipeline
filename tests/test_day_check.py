"""Tests for the DAG's check that a UTC day was collected (orchestration/dags/day_check.py)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestration" / "dags"))
import day_check  # noqa: E402


def files(tmp_path, day, hours, store=True):
    for h in hours:
        p = tmp_path / "raw" / "players" / f"date={day}" / f"hour={h:02d}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"records": [{"appid": 730}]}')
    if store:
        p = tmp_path / "raw" / "store" / f"date={day}" / "store.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"records": [{"appid": 730}]}')
    return tmp_path


def test_a_full_day_passes_without_warnings(tmp_path):
    r = day_check.check_day(files(tmp_path, "2026-11-05", range(24)), "2026-11-05")
    assert r["hours"] == 24 and r["warnings"] == []


def test_a_day_with_gaps_passes_and_names_the_missing_hours(tmp_path):
    r = day_check.check_day(files(tmp_path, "2026-11-03", [13, 20]), "2026-11-03")
    assert r["hours"] == 2 and "missing hours (UTC): 00, 01" in r["warnings"][0] and "13" not in r["warnings"][0]


@pytest.mark.parametrize("hours, store, message", [([], True, "no hourly player files"),
                                                    ([5], False, "no store file")])
def test_a_day_not_collected_yet_fails_so_airflow_retries(tmp_path, hours, store, message):
    with pytest.raises(ValueError, match=message):
        day_check.check_day(files(tmp_path, "2026-11-05", hours, store), "2026-11-05")


def test_empty_files_count_as_missing(tmp_path):
    files(tmp_path, "2026-11-05", [1, 2])
    (tmp_path / "raw" / "players" / "date=2026-11-05" / "hour=02.json").write_text('{"records": []}')
    (tmp_path / "raw" / "store" / "date=2026-11-05" / "store.json").write_text('{"records": []}')
    with pytest.raises(ValueError, match="no store file"):
        day_check.check_day(tmp_path, "2026-11-05")
