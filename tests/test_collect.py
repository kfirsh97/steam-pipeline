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


def fake_sources(monkeypatch, players=None, store=None, top=None, charts=None):
    """Answer like the three sources. players / store: {appid: answer}; a missing game gets a 404."""
    calls = []

    def get(url, params=None, timeout=None):
        calls.append((url, params))
        if url == collect.CHARTS_URL:
            return FakeResponse(200, {"response": {"ranks": charts}}) if charts else FakeResponse(404)
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


def chart(appids):
    """Steam's chart answer for these games, in this rank order, padded to a full list."""
    ids = list(appids) + [10_000 + n for n in range(max(0, 60 - len(appids)))]
    return [{"rank": n, "appid": a, "peak_in_game": 1000} for n, a in enumerate(ids, 1)]


def test_top_games_comes_from_steam_in_rank_order(monkeypatch):
    ranks = chart([730, 570])
    ranks[0]["rank"], ranks[1]["rank"] = 2, 1                       # answered out of order
    fake_sources(monkeypatch, charts=ranks, top={"440": {"name": "Team Fortress 2"}})
    games, fallback = collect.top_games()
    assert [(g["appid"], g["source"]) for g in games[:2]] == [(570, "steam"), (730, "steam")] and fallback is None


def test_a_short_steam_list_falls_back_to_the_saved_list_not_steamspy(monkeypatch, tmp_path):
    saved = tmp_path / "raw" / "top_games" / "date=2026-11-05" / "top_games.json"
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps({"games": [{"appid": 570, "rank": 1, "source": "steam"}]}))
    calls = fake_sources(monkeypatch, charts=[{"rank": 1, "appid": 730}], top={"440": {}})
    games, fallback = collect.top_games(tmp_path)
    assert [g["appid"] for g in games] == [570] and "date=2026-11-05" in fallback
    assert not any(url == collect.TOP_URL for url, _ in calls)


def test_steamspy_only_when_there_is_no_saved_list(monkeypatch):
    fake_sources(monkeypatch, top={"730": {"name": "Counter-Strike 2"}, "440": {"name": "Team Fortress 2"}})
    games, fallback = collect.top_games()
    assert [(g["appid"], g["name"]) for g in games] == [(730, "Counter-Strike 2"), (440, "Team Fortress 2")]
    assert "SteamSpy" in fallback


def test_a_daily_run_on_a_fallback_list_saves_the_day_but_fails(monkeypatch, tmp_path):
    fake_sources(monkeypatch, top={"730": {}}, store={730: {"name": "Counter-Strike 2"}})
    assert collect.main(["daily", "--out", str(tmp_path)]) == 1
    assert json.loads(next(tmp_path.rglob("store.json")).read_text())["records"][0]["appid"] == 730


def test_one_failed_game_does_not_stop_the_others_and_zero_is_suspicious(monkeypatch, tmp_path):
    fake_sources(monkeypatch, players={730: 0, 570: 500_000, 440: 80_000, 578080: 300_000, 1172470: 90_000},
                 top={"730": {}, "570": {}, "440": {}, "578080": {}, "1172470": {}, "1": {}})
    path, saved, failed = collect.run_players(tmp_path)
    data = json.loads(path.read_text())
    assert (saved, failed) == (5, 1) and data["failures"][0]["appid"] == 1
    assert [(r["appid"], r["answer"], r["suspicious"]) for r in data["records"][:2]] == [(730, 0, True),
                                                                                       (570, 500_000, False)]
    assert path.parent.name.startswith("date=") and path.name.startswith("hour=")


def test_a_worse_second_run_in_the_same_hour_keeps_the_better_file(monkeypatch, tmp_path):
    fake_sources(monkeypatch, players={730: 900_000, 570: 600_000}, top={"730": {}, "570": {}})
    path, _, _ = collect.run_players(tmp_path)
    fake_sources(monkeypatch, players={730: 0, 570: 600_000}, top={"730": {}, "570": {}})   # a zero this time
    collect.run_players(tmp_path)
    assert [r["answer"] for r in json.loads(path.read_text())["records"]] == [900_000, 600_000]
    fake_sources(monkeypatch, players={730: 950_000, 570: 610_000, 440: 1}, top={"730": {}, "570": {}, "440": {}})
    collect.run_players(tmp_path)                                                        # a better one wins
    assert len(json.loads(path.read_text())["records"]) == 3


def test_a_second_daily_run_keeps_store_answers_of_games_it_did_not_get(monkeypatch, tmp_path):
    def answers(ranks, names):
        return {**{r["appid"]: {"name": f"Game {r['appid']}"} for r in ranks}, **names}
    first = chart([730, 440])
    fake_sources(monkeypatch, charts=first, store=answers(first, {730: {"name": "CS2"}, 440: {"name": "TF2"}}))
    collect.run_daily(tmp_path)
    second = chart([730, 570])                  # Team Fortress 2 left the list; Dota 2 joined
    fake_sources(monkeypatch, charts=second, store=answers(second, {730: {"name": "CS2 new"}, 570: {"name": "Dota 2"}}))
    collect.run_daily(tmp_path)
    records = json.loads(next(tmp_path.rglob("store.json")).read_text())["records"]
    names = {r["appid"]: r["answer"]["name"] for r in records}
    assert names[730] == "CS2 new" and names[440] == "TF2" and names[570] == "Dota 2"
    assert len(records) == len({r["appid"] for r in records})          # one answer per game


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
    ranks = chart([730, 440])
    store = {r["appid"]: {"name": f"Game {r['appid']}"} for r in ranks}
    store.update({730: {"name": "Counter-Strike 2", "is_free": True, "detailed_description": "long text"},
                  440: {"name": "Team Fortress 2", "price_overview": {"final": 0}}})
    fake_sources(monkeypatch, charts=ranks, store=store, players={r["appid"]: 1 for r in ranks})
    assert collect.main(["daily", "--out", str(tmp_path)]) == 0
    store = json.loads(next(tmp_path.rglob("store.json")).read_text())
    assert store["records"][0]["answer"]["is_free"] is True
    assert "detailed_description" not in store["records"][0]["answer"]          # long texts are dropped
    calls = fake_sources(monkeypatch, players={r["appid"]: 1 for r in ranks}, top=None)   # no lists answer now
    assert collect.main(["players", "--out", str(tmp_path)]) == 0
    assert not any(url == collect.TOP_URL for url, _ in calls)


def test_the_backup_daily_run_does_nothing_when_today_is_collected(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    today = tmp_path / "raw" / "store" / f"date={datetime.now(timezone.utc):%Y-%m-%d}" / "store.json"
    today.parent.mkdir(parents=True)
    today.write_text('{"records": []}')
    calls = fake_sources(monkeypatch)
    assert collect.main(["daily", "--out", str(tmp_path), "--if-missing"]) == 0 and calls == []
