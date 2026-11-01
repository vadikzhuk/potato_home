"""settings.yaml: how often to check and when to call a bot stuck.

It is read again before every check, so saving the file is all it takes.
A mistake in it gives a clear message instead of a crash later on.
"""

import os
from pathlib import Path

import yaml

from .core import Invalid

SERVICE_DIR = Path(__file__).resolve().parent.parent  # services/botwatch when run from the repo
NUMBERS = ("check_every_seconds", "stuck_after_minutes", "memory_warn_percent", "keep_checks_days", "keep_usage_days")


def path() -> Path:
    return Path(os.environ.get("BOTWATCH_SETTINGS") or SERVICE_DIR / "settings.yaml")


def load(file: Path | None = None) -> dict:
    file = file or path()
    try:
        settings = yaml.safe_load(file.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise Invalid(f"Can't read {file.name}: {error}") from None
    check(settings)
    return settings


def check(settings) -> None:
    """Raise Invalid naming everything that's wrong, if anything is."""
    if not isinstance(settings, dict):
        raise Invalid("settings.yaml should be a list of `name: value` lines")
    wrong = [name for name in NUMBERS
             if isinstance(settings.get(name), bool) or not isinstance(settings.get(name), (int, float))
             or settings[name] <= 0]
    if wrong:
        raise Invalid("settings.yaml: these should be numbers above 0: " + ", ".join(wrong))
    if settings["check_every_seconds"] < 10:
        raise Invalid("settings.yaml: check_every_seconds should be at least 10")
