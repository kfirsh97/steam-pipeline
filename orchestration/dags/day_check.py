"""Did the collector capture a given UTC day? Used by the DAG before loading, and tested on its own."""
import json
from pathlib import Path

MIN_HOURS = 1           # below this the day is treated as not collected yet (the DAG retries)
WARN_HOURS = 20         # below this the day is loaded, but the gap is reported


def check_day(data_dir, day):
    """{"day", "hours", "store", "warnings"} for one UTC day (YYYY-MM-DD). Raises ValueError if the day has no
    hourly files or no store file yet, so the task fails and is retried later."""
    raw = Path(data_dir) / "raw"
    # A file counts only if it holds records: an empty hour or store file is the same as a missing one.
    hours = sorted(p.stem.removeprefix("hour=") for p in (raw / "players" / f"date={day}").glob("hour=*.json")
                   if _records(p))
    store_file = raw / "store" / f"date={day}" / "store.json"
    store = store_file.exists() and _records(store_file) > 0
    if len(hours) < MIN_HOURS:
        raise ValueError(f"{day}: no hourly player files yet")
    if not store:
        raise ValueError(f"{day}: no store file yet (the daily job runs at 00:15 UTC)")
    warnings = []
    if len(hours) < WARN_HOURS:
        missing = sorted(set(f"{h:02d}" for h in range(24)) - set(hours))
        warnings.append(f"{day}: only {len(hours)} of 24 hours collected; missing hours (UTC): {', '.join(missing)}")
    return {"day": day, "hours": len(hours), "store": store, "warnings": warnings}


def _records(path):
    try:
        return len(json.loads(path.read_text()).get("records") or [])
    except (OSError, ValueError):
        return 0
