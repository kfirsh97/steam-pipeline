"""Tests for collect.py with fake sources: no network, no waiting."""
import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect  # noqa: E402


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        raise requests.HTTPError(f"{self.status_code} error")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)


def fake_sources(monkeypatch, players=None, store=None, top=None):
    """Answer like the three sources. players / store: {appid: answer}; a missing game gets a 404."""
    calls = []

    def get(url, params=None, timeout=None):
        calls.append((url, params))
        if url == collect.TOP_URL:
            return FakeResponse(200, top)
        if url == collect.PLAYERS_URL:
            count = (players or {}).get(params["appid"])
            if count is None:
                return FakeResponse(404)
            return FakeResponse(200, {"response": {"player_count": count, "result": 1}})
        if url == collect.STORE_URL:
            data = (store or {}).get(params["appids"])
            if data is None:
                return FakeResponse(200, {str(params["appids"]): {"success": False}})
            return FakeResponse(200, {str(params["appids"]): {"success": True, "data": data}})
        raise AssertionError(url)

    monkeypatch.setattr(collect.requests, "get", get)
    return calls


def test_retries_a_busy_source_then_gives_up(monkeypatch):
    answers = [FakeResponse(503), FakeResponse(429), FakeResponse(200, {"ok": 1})]
    monkeypatch.setattr(collect.requests, "get", lambda *a, **k: answers.pop(0))
    assert collect.get_json("https://x") == {"ok": 1}
    monkeypatch.setattr(collect.requests, "get", lambda *a, **k: FakeResponse(503))
    with pytest.raises(RuntimeError, match="failed 4 times: status 503"):
        collect.get_json("https://x")


def test_does_not_retry_a_missing_page(monkeypatch):
    calls = []
    monkeypatch.setattr(collect.requests, "get", lambda *a, **k: calls.append(1) or FakeResponse(404))
    with pytest.raises(requests.HTTPError):
        collect.get_json("https://x")
    assert len(calls) == 1


def test_top_games_turns_text_keys_into_numbers_and_keeps_the_order(monkeypatch):
    fake_sources(monkeypatch, top={"730": {"name": "Counter-Strike 2"}, "440": {"name": "Team Fortress 2"}})
    assert [(g["appid"], g["name"]) for g in collect.top_games()] == [(730, "Counter-Strike 2"),
                                                                       (440, "Team Fortress 2")]


def test_one_failed_game_does_not_stop_the_others_and_zero_is_suspicious(monkeypatch, tmp_path):
    fake_sources(monkeypatch, players={730: 0, 570: 500_000, 440: 80_000, 578080: 300_000, 1172470: 90_000},
                 top={"730": {}, "570": {}, "440": {}, "578080": {}, "1172470": {}, "1": {}})
    path, saved, failed = collect.run_players(tmp_path)
    data = json.loads(path.read_text())
    assert (saved, failed) == (5, 1) and data["failures"][0]["appid"] == 1
    assert [(r["appid"], r["answer"], r["suspicious"]) for r in data["records"][:2]] == [(730, 0, True),
                                                                                       (570, 500_000, False)]
    assert path.parent.name.startswith("date=") and path.name.startswith("hour=")


def test_running_the_same_hour_twice_keeps_one_file(monkeypatch, tmp_path):
    fake_sources(monkeypatch, players={730: 1}, top={"730": {}})
    first, _, _ = collect.run_players(tmp_path)
    second, _, _ = collect.run_players(tmp_path)
    assert first == second and len(list(tmp_path.rglob("*.json"))) == 1
    assert not list(tmp_path.rglob("*.tmp"))


def test_too_many_failures_fail_the_run_but_keep_what_was_collected(monkeypatch, tmp_path):
    fake_sources(monkeypatch, players={730: 1}, top={"730": {}, "1": {}, "2": {}})
    assert collect.main(["players", "--out", str(tmp_path)]) == 1
    data = json.loads(next(tmp_path.rglob("hour=*.json")).read_text())
    assert len(data["records"]) == 1 and len(data["failures"]) == 2


def test_the_hourly_job_follows_the_list_the_daily_job_saved(monkeypatch, tmp_path):
    fake_sources(monkeypatch, top={"730": {"name": "Counter-Strike 2"}, "440": {}},
                 store={730: {"name": "Counter-Strike 2", "is_free": True, "detailed_description": "long text"},
                        440: {"name": "Team Fortress 2", "price_overview": {"final": 0}}},
                 players={730: 1, 440: 2})
    assert collect.main(["daily", "--out", str(tmp_path)]) == 0
    store = json.loads(next(tmp_path.rglob("store.json")).read_text())
    assert store["records"][0]["answer"]["is_free"] is True
    assert "detailed_description" not in store["records"][0]["answer"]          # long texts are dropped
    calls = fake_sources(monkeypatch, players={730: 1, 440: 2}, top=None)         # SteamSpy down now
    assert collect.main(["players", "--out", str(tmp_path)]) == 0
    assert not any(url == collect.TOP_URL for url, _ in calls)
