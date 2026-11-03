import time
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import requests

# Source: current players per game, Steam Web API
PLAYERS_URL = (
    "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
)
ATTEMPTS = 4
PAUSE_S = 0.3


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


def current_players(appid):
    """Current player count for one game. Raises an error if Steam has no count for it."""
    answer = get_json(PLAYERS_URL, {"appid": appid})
    inner = answer["response"]
    if inner["result"] != 1:
        raise RuntimeError(f"Steam has no player count for game {appid}")
    return inner["player_count"]


def collect_players(appids):
    """Player counts for many games. A game that fails is listed in failures and doesn't stop the others."""
    records = []
    failures = []
    for appid in appids:
        time.sleep(PAUSE_S)
        try:
            count = current_players(appid)
        except Exception as error:
            failures.append({"appid": appid, "error": str(error)})
            continue
        records.append(
            {
                "appid": appid,
                "player_count": count,
                "suspicious": count == 0,
                "collected_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            }
        )
    return records, failures


def save_players(records, failures, started, out):
    """Save one run as raw/players/date=YYYY-MM-DD/hour=HH.json. Re-running the same hour replaces the file."""
    path = (
        Path(out)
        / "raw"
        / "players"
        / f"date={started:%Y-%m-%d}"
        / f"hour={started:%H}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    playload = {
        "started_at": started.isoformat(timespec="seconds"),
        "records": records,
        "failures": failures,
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(playload, indent=2))
    os.replace(temporary, path)
    return path


if __name__ == "__main__":
    started = datetime.now(timezone.utc)
    records, failures = collect_players([730, 570, 440, 1])
    path = save_players(records, failures, started, "store")
    print(f"saved {len(records)} games, {len(failures)} failed -> {path}")
