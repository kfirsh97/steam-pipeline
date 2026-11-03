import time

import requests

# Source: current players per game, Steam Web API
PLAYERS_URL = (
    "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
)
ATTEMPTS = 4


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


if __name__ == "__main__":
    print(current_players(570))
