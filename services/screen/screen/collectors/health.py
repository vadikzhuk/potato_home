"""Health of our home services: each one answers GET /health.

Every check gets one of four states:
  ok    answered quickly with {"status": "ok"}
  slow  answered, but slower than `slow_ms`
  warn  answered {"status": "degraded", "detail": ...}: running, but something it needs is not
  down  no answer, an error, or not HTTP 200

The last 10 states of every service are kept between checks, so the screen shows
not only how a service is now but also one that keeps failing every now and then.
"""

import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

HISTORY = 10

# Kept between runs: service name -> recent states, and since when the current state lasts
history: dict[str, deque] = {}
state_since: dict[str, tuple[str, datetime]] = {}


def fetch(config: dict) -> dict:
    settings = config["health"]
    now = datetime.now(ZoneInfo(config["timezone"]))
    services = []
    for service in settings["services"]:
        state, ms, detail = check(service["url"], settings["slow_ms"], settings["timeout_seconds"])
        services.append(remember(service["name"], state, ms, detail, now))
    return {"services": services}


def check(url: str, slow_ms: int, timeout: float) -> tuple[str, int | None, str]:
    """Ask one service. Returns (state, milliseconds or None, detail)."""
    started = time.monotonic()
    try:
        response = httpx.get(url, timeout=timeout)
    except httpx.TimeoutException:
        return "down", None, f"no answer in {timeout:g} s"
    except httpx.ConnectError:
        return "down", None, "can't connect"
    except httpx.HTTPError as error:
        return "down", None, type(error).__name__
    ms = round((time.monotonic() - started) * 1000)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return classify(response.status_code, body, ms, slow_ms)


def classify(status_code: int, body: dict, ms: int, slow_ms: int) -> tuple[str, int, str]:
    if status_code != 200:
        return "down", ms, body.get("detail") or f"HTTP {status_code}"
    if body.get("status") == "degraded":
        return "warn", ms, body.get("detail") or "degraded"
    if ms > slow_ms:
        return "slow", ms, "slow to answer"
    return "ok", ms, "ok"


def remember(name: str, state: str, ms: int | None, detail: str, now: datetime) -> dict:
    """Add this result to the service's history and return what the screen shows."""
    recent = history.setdefault(name, deque(maxlen=HISTORY))
    recent.append(state)
    if state_since.get(name, (None,))[0] != state:
        state_since[name] = (state, now)
    since = state_since[name][1]
    return {
        "name": name,
        "state": state,
        "ms": ms,
        "detail": detail,
        "history": list(recent),
        "since": None if state == "ok" else since.strftime("%H:%M"),
    }


def source_row(name: str, panel: dict, slow_ms: int) -> dict:
    """The same kind of row for an outside data source (weather, news), from what its
    collector last did, so we don't ask those websites twice."""
    if panel["error"]:
        state, detail = "down", panel["error"]
    elif panel["updated"] is None:
        state, detail = "wait", "not loaded yet"
    elif (panel["took_ms"] or 0) > slow_ms:
        state, detail = "slow", "slow to answer"
    else:
        state, detail = "ok", "ok"
    updated = panel["updated"].strftime("%H:%M") if panel["updated"] else "-"
    return {"name": name, "state": state, "ms": panel["took_ms"], "detail": detail, "updated": updated}
