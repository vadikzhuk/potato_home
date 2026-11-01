"""The background loop of the botwatch service: checks every bot, again and again.

It runs inside the API process, so the service is the only program writing the database.
What the loop itself last managed (or not) is kept in `last_round` for /health.
"""

import logging
import threading
import time

from . import core, db, settings as settings_file
from .docker import Docker, DockerError
from .telegram import Telegram

log = logging.getLogger(__name__)
PRUNE_EVERY = 3600  # seconds

# monotonic time of the last complete round, and what went wrong in the latest one
last_round = {"at": None, "problem": None, "every": 60}


def watch(stop: threading.Event, docker: Docker | None = None, telegram: Telegram | None = None) -> None:
    docker, telegram = docker or Docker(), telegram or Telegram()
    last_prune = 0.0
    while not stop.is_set():
        started = time.monotonic()
        every = last_round["every"]
        try:
            settings = settings_file.load()
            every = last_round["every"] = settings["check_every_seconds"]
            prune = started - last_prune > PRUNE_EVERY
            run_round(docker, telegram, settings, prune)
            if prune:
                last_prune = started
            last_round.update(at=time.monotonic(), problem=None)
        except (core.Invalid, DockerError) as error:
            log.warning("Check skipped: %s", error)
            last_round["problem"] = str(error)
        except Exception:
            log.exception("Check failed")
            last_round["problem"] = "the last check failed: see docker compose logs botwatch"
        stop.wait(max(1.0, every - (time.monotonic() - started)))


def run_round(docker: Docker, telegram: Telegram, settings: dict, prune: bool = False) -> list[dict]:
    conn = db.connect()
    try:
        checked = core.check_all(conn, docker, telegram, settings)
        if prune:
            core.prune(conn, settings)
        return checked
    finally:
        conn.close()


def start() -> threading.Event:
    """Start watching in a background thread; set the returned event to stop."""
    stop = threading.Event()
    threading.Thread(target=watch, args=(stop,), daemon=True, name="botwatch").start()
    return stop
