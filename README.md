# Raw data

Written by the collection jobs on the main branch (`collect.py`), one file per run, never edited by hand.

- `raw/players/date=YYYY-MM-DD/hour=HH.json` - every hour: current players per tracked game (UTC hour)
- `raw/top_games/date=YYYY-MM-DD/top_games.json` - every day: SteamSpy's 100 most played games of the last two weeks
- `raw/store/date=YYYY-MM-DD/store.json` - every day: each tracked game's price, discount, genres and release date

Each run file holds `records` (one per game that answered, with Steam's answer as it came) and `failures` (the
games that didn't, and why).
