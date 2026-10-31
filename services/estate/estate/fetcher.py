"""Fetching: asking every source for listings and saving them.

It runs by itself once a day at criteria.yaml's fetch time (see daily()),
or right now with `estate fetch`. One fetch at a time in this process.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime

from . import core, criteria, db
from .sources import SOURCES, web

log = logging.getLogger(__name__)
_running = threading.Lock()


class Busy(core.EstateError):
    pass


def run(conn, settings: dict, sources: dict | None = None,
        say: Callable[[str], None] = log.info) -> dict:
    """Fetch from all sources (or the given ones), save, link duplicates. Returns the run."""
    if not _running.acquire(blocking=False):
        raise Busy("A fetch is already running.")
    try:
        run_id = core.start_run(conn)
        seen = added = 0
        errors = []
        pause = lambda: time.sleep(settings["fetch"]["pause_seconds"])  # noqa: E731
        with web.client() as http:
            for name, source in (sources or SOURCES).items():
                count = 0
                try:
                    for listing in source.fetch(settings["search"], http, pause):
                        added += core.save_listing(conn, listing)
                        count += 1
                except Exception as error:  # a broken site must not stop the others
                    errors.append(f"{name}: {type(error).__name__}: {error}")
                    say(f"{name}: failed after {count} listings: {error}")
                else:
                    say(f"{name}: {count} listings")
                seen += count
        linked = core.link_duplicates(conn, settings)
        say(f"{added} new, {linked} duplicates found")
        return core.finish_run(conn, run_id, seen, added, errors)
    finally:
        _running.release()


def start(settings: dict) -> None:
    """Fetch in the background, now. Returns at once; raises Busy if a fetch is running."""
    if _running.locked():
        raise Busy("A fetch is already running.")

    def work():
        conn = db.connect()
        try:
            run(conn, settings)
        except Busy:
            pass  # another one started in the meantime: fine
        finally:
            conn.close()

    threading.Thread(target=work, daemon=True, name="fetch-now").start()


def is_due(conn, settings: dict, moment: datetime) -> bool:
    """Is it past today's fetch time, with no fetch started today yet?"""
    if moment.strftime("%H:%M") < settings["fetch"]["time"]:
        return False
    last = conn.execute("SELECT started_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if last is None:
        return True
    started = datetime.fromisoformat(last["started_at"]).astimezone(core.LOCAL_TZ)
    return started.date() < moment.date()


def daily(stop: threading.Event) -> None:
    """Runs in the background of the API: once a minute, is today's fetch due?

    A machine that was off at fetch time catches up when it starts.
    """
    while not stop.wait(60):
        conn = db.connect()
        try:
            settings = criteria.load()
            if is_due(conn, settings, datetime.now(core.LOCAL_TZ)):
                log.info("Daily fetch starts")
                result = run(conn, settings)
                log.info("Daily fetch done: %s seen, %s new", result["seen"], result["added"])
        except Exception:  # keep the loop alive whatever happens; the log says what
            log.exception("Daily fetch failed")
        finally:
            conn.close()
