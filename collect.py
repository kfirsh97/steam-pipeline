"""Step 1 of the pipeline: collect raw Steam data and save each run as one file.

Two jobs, scheduled in .github/workflows/:

    python collect.py players   every hour: how many people play each tracked game right now
    python collect.py daily     once a day: the top-100 list, and each game's price, discount and genres

Which games: Steam's own list of the 100 most played games (ISteamChartsService). If it doesn't answer, the
last saved list is kept (and the run is marked failed); SteamSpy only when there is no saved list at all. SteamSpy was the first source, but in the first three days its answer never changed
(the same numbers, old names like "Counter-Strike: Global Offensive") and it left out Dota 2 - one of the most
played games on Steam.

Rules a collector needs:
- Nothing collected today can be collected later, so one failed game doesn't stop the others. Failures are
  saved in the same file, and the run fails (red in GitHub Actions) only if more than MAX_FAILED_SHARE failed.
- Requests are retried on timeouts, 429 and 5xx, and spaced out to stay under each source's rate limit.
- A file is named by the UTC hour or day it holds, so a re-run never adds a second copy, and it is written in one
  step, so a crash never leaves half a file. A second run in the same hour replaces the file only if it has more
  real counts; a second daily run adds its store answers to the first run's instead of dropping games.
- A player count of 0 is kept but marked suspicious: Steam sometimes answers 0 with "success" for a game that
  has hundreds of thousands of players (seen for Counter-Strike 2 on 2026-11-03).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Sources
PLAYERS_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
CHARTS_URL = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"
TOP_URL = "https://steamspy.com/api.php"  # the fallback list
STORE_URL = "https://store.steampowered.com/api/appdetails"

ATTEMPTS = 4
PLAYERS_PAUSE_S = 0.3  # between games, Steam Web API
STORE_PAUSE_S = 1.6  # the store allows about 200 requests in 5 minutes
MAX_FAILED_SHARE = 0.2
# The store's answer is long (descriptions, images, videos); only these fields are kept.
STORE_FIELDS = ["name", "type", "is_free", "price_overview", "genres", "categories",
                "release_date", "developers", "publishers"]


def get_json(url, params=None):
    """GET a JSON answer. Retries timeouts, 429 and 5xx, waiting 1s, 2s, 4s between tries."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=20)
        except (requests.Timeout, requests.ConnectionError) as error:
            problem = f"no answer: {error}"
        else:
            if response.status_code == 200:
                return response.json()
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
            problem = f"status {response.status_code}"
        if attempt < ATTEMPTS:
            wait = 2 ** (attempt - 1)
            print(f"attempt {attempt} failed ({problem}), waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"{url} failed {ATTEMPTS} times: {problem}")


MIN_LIST = 50  # a "top 100" shorter than this is treated as a failed answer


def top_games(out=None):
    """(games, fallback) - the 100 most played games, most played first, and why a fallback was used (or None).
    Steam's own chart first. If it fails or is too short: the last list saved under out (yesterday's, usually),
    and only with no saved list SteamSpy's, which is frozen and misses games. A fallback still collects the day,
    but the run is marked failed, so someone looks."""
    try:
        return steam_top_games(), None
    except Exception as error:
        reason = f"Steam's most-played list failed ({error})"
    saved = sorted(Path(out).glob("raw/top_games/date=*/top_games.json")) if out else []
    if saved:
        games = json.loads(saved[-1].read_text())["games"]
        return games, f"{reason}; kept the list saved in {saved[-1].parent.name}"
    return steamspy_top_games(), f"{reason}; used SteamSpy's list (no saved list yet)"


def steam_top_games():
    """Steam's most played games by peak players at once: rank, appid, peak_in_game, last_week_rank."""
    answer = get_json(CHARTS_URL)
    ranks = (answer.get("response") or {}).get("ranks") if isinstance(answer, dict) else None
    if not ranks:
        raise RuntimeError("Steam returned no ranks")
    games = sorted(({**r, "appid": int(r["appid"]), "source": "steam"} for r in ranks), key=lambda g: g["rank"])
    if len(games) < MIN_LIST:
        raise RuntimeError(f"Steam's list has only {len(games)} games")
    return games[:100]


def steamspy_top_games():
    """SteamSpy's 100 most played games of the last two weeks, in its order."""
    answer = get_json(TOP_URL, {"request": "top100in2weeks"})
    if not isinstance(answer, dict) or not answer:
        raise RuntimeError("SteamSpy returned no games")
    games = []
    for key in answer:  # the keys are game numbers written as text, e.g. "730"
        games.append({**answer[key], "appid": int(key), "source": "steamspy"})
    return games


def current_players(appid):
    """Current player count for one game. Raises an error if Steam has no count for it."""
    answer = get_json(PLAYERS_URL, {"appid": appid})
    inner = answer["response"]
    if inner["result"] != 1:
        raise RuntimeError(f"Steam has no player count for game {appid}")
    return inner["player_count"]


def store_details(appid):
    """Price, discount, genres and release date for one game, in US dollars, as the store answers them."""
    answer = get_json(STORE_URL, {"appids": appid, "cc": "us", "l": "english"})
    entry = answer.get(str(appid)) if isinstance(answer, dict) else None
    if not entry or not entry.get("success"):
        raise RuntimeError(f"the store has no details for game {appid}")
    data = entry["data"]
    return {field: data.get(field) for field in STORE_FIELDS}


def collect(appids, fetch, pause_s):
    """Run fetch(appid) for every game. A game that fails is listed in failures and doesn't stop the others."""
    records = []
    failures = []
    for appid in appids:
        time.sleep(pause_s)
        try:
            answer = fetch(appid)
        except Exception as error:
            failures.append({"appid": appid, "error": str(error)[:300]})
            continue
        records.append(
            {
                "appid": appid,
                "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "answer": answer,
            }
        )
    return records, failures


def save(path, payload):
    """Write JSON in one step: a temporary file, then a rename. An existing file is replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False))
    os.replace(temporary, path)


def check(job, total, failures):
    """Fail the run if too many games failed: a partial file is saved, but someone should look."""
    if total == 0:
        raise RuntimeError(f"{job}: there were no games to collect")
    if len(failures) / total > MAX_FAILED_SHARE:
        raise RuntimeError(f"{job}: {len(failures)} of {total} games failed; first error: {failures[0]['error']}")


def tracked_games(out):
    """The games to follow: the latest top-100 list the daily job saved, or a fresh one if there is none yet."""
    saved = sorted(Path(out).glob("raw/top_games/date=*/top_games.json"))
    if saved:
        return [game["appid"] for game in json.loads(saved[-1].read_text())["games"]]
    return [game["appid"] for game in top_games()[0]]


def usable(payload):
    """How many real player counts a saved hour holds (answers, without the suspicious zeros)."""
    return sum(1 for r in payload["records"] if not r.get("suspicious"))


def run_players(out):
    """Every tracked game's player count, saved as raw/players/date=YYYY-MM-DD/hour=HH.json (UTC)."""
    started = datetime.now(timezone.utc)
    appids = tracked_games(out)
    records, failures = collect(appids, current_players, PLAYERS_PAUSE_S)
    for record in records:
        record["suspicious"] = record["answer"] == 0
    path = Path(out) / "raw" / "players" / f"date={started:%Y-%m-%d}" / f"hour={started:%H}.json"
    payload = {"started_at": started.isoformat(timespec="seconds"), "records": records, "failures": failures}
    # Two runs in one hour (the outside scheduler and GitHub's own): keep whichever file has more real counts,
    # so a late run with many zeros or failures never replaces a good one.
    if path.exists() and usable(json.loads(path.read_text())) >= usable(payload):
        print(f"{path.name}: an earlier run this hour has as many real counts or more - kept it")
    else:
        save(path, payload)
    check("players", len(appids), failures)
    return path, len(records), len(failures)


def run_daily(out):
    """Today's top-100 list, then every listed game's store details, under raw/top_games and raw/store (UTC day)."""
    started = datetime.now(timezone.utc)
    day = f"date={started:%Y-%m-%d}"
    games, fallback = top_games(out)
    listed = {"collected_at": started.isoformat(timespec="seconds"), "games": games}
    if fallback:
        listed["fallback"] = fallback
    save(Path(out) / "raw" / "top_games" / day / "top_games.json", listed)
    appids = [game["appid"] for game in games]
    records, failures = collect(appids, store_details, STORE_PAUSE_S)
    path = Path(out) / "raw" / "store" / day / "store.json"
    # A second run the same day adds to the first: its answers replace the earlier ones game by game, and games
    # only the earlier run had (it followed another list, or this run failed them) keep their answers.
    if path.exists():
        earlier = json.loads(path.read_text())
        fresh = {r["appid"] for r in records}
        records += [r for r in earlier["records"] if r["appid"] not in fresh]
        failures = [f for f in failures if f["appid"] not in {r["appid"] for r in records}]
    save(path, {"started_at": started.isoformat(timespec="seconds"), "records": records, "failures": failures})
    check("store", len(appids), failures)
    if fallback:
        raise RuntimeError(f"collected with a fallback list: {fallback}")
    return path, len(records), len(failures)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect raw Steam data.")
    parser.add_argument("job", choices=["players", "daily"])
    parser.add_argument("--out", default="store", help="the folder that holds raw/")
    parser.add_argument("--if-missing", action="store_true",
                        help="daily only: do nothing if today's store file already exists (the backup schedule)")
    args = parser.parse_args(argv)
    if args.job == "daily" and args.if_missing:
        today = Path(args.out) / "raw" / "store" / f"date={datetime.now(timezone.utc):%Y-%m-%d}" / "store.json"
        if today.exists():
            print(f"daily: {today} already exists - the backup run has nothing to do")
            return 0
    run = run_players if args.job == "players" else run_daily
    try:
        path, saved, failed = run(args.out)
    except Exception as error:
        print(f"{args.job} failed: {error}", file=sys.stderr)
        return 1
    print(f"{args.job}: saved {saved} games, {failed} failed -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
