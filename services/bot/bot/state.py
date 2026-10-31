"""The bot's small memory between restarts: one JSON file of named values.

  {"last_event_id": 41, "estate_last_run": 3}

Each part of the bot keeps its own key, so they never overwrite each other.
"""

import json
import os
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]  # services/bot when run from the repo


def path() -> Path:
    """BOT_STATE from the environment, or potato_home/data/bot/state.json locally."""
    return Path(os.environ.get("BOT_STATE") or SERVICE_DIR.parent.parent / "data" / "bot" / "state.json")


def _read() -> dict:
    try:
        return json.loads(path().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def load(key: str):
    """The value saved under `key`, or None."""
    return _read().get(key)


def save(key: str, value) -> None:
    data = _read()
    data[key] = value
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data))
