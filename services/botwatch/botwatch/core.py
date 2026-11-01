"""What botwatch finds out about the bots and what it makes of it.

Every check of a bot (once a minute by default) looks at:
  1. Docker: is its container running, since when, did it crash, memory and CPU
  2. Telegram: is the token accepted, do messages pile up (= the bot is stuck),
     is a webhook set that keeps polling from getting anything
  3. its log since the previous check: errors

Problems become alerts for the admins twice: when they appear and when they are gone.
Alerts are only stored here; the home bot sends them in Telegram.

Usage comes from botstats.py inside the bots: one event per update a bot handled.
"""

import logging
import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .docker import Docker, DockerError, scan_errors
from .telegram import Telegram, TelegramProblem

log = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Riga")
CURRENT = timedelta(minutes=15)  # a bot not checked this long before the newest check is gone
RESTART_ALERT_EVERY = timedelta(hours=1)  # a bot that keeps crashing gets one restart alert an hour


class BotwatchError(Exception):
    """An error with a message meant for the person using botwatch."""


class NotFound(BotwatchError):
    pass


class Invalid(BotwatchError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(text: str) -> datetime:
    return datetime.fromisoformat(text)


def local_midnight(at: datetime) -> datetime:
    return at.astimezone(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)


# --- Checking -------------------------------------------------------------------

def check_all(conn: sqlite3.Connection, docker: Docker, telegram: Telegram, settings: dict,
              at: datetime | None = None) -> list[dict]:
    """Check every bot container once. Raises DockerError when Docker can't be asked at all."""
    at = at or utcnow()
    checked = []
    for bot in docker.bots():
        try:
            checked.append(check_bot(conn, bot, docker, telegram, settings, at))
        except DockerError as error:  # e.g. the container was removed a moment ago
            log.warning("Can't check %s: %s", bot["name"], error)
    return checked


def check_bot(conn, bot: dict, docker: Docker, telegram: Telegram, settings: dict, at: datetime) -> dict:
    previous = last_check(conn, bot["name"])
    info = docker.inspect(bot["id"])
    running = info["state"] == "running"
    row = {
        "bot": bot["name"], "at": iso(at), "container": info["id"], "state": info["state"],
        "started_at": info["started_at"], "restarts": info["restarts"],
        "username": previous["username"] if previous else None,
        "memory_mb": None, "memory_limit_mb": None, "cpu_percent": None, "pending": None,
    }
    problems = []

    if not running:
        problems.append(not_running(info))
    elif info["health"] == "unhealthy":
        problems.append("its Docker healthcheck fails")
    if running:
        row.update(docker.stats(bot["id"]))
        limit = row["memory_limit_mb"]
        if row["memory_mb"] and limit and row["memory_mb"] >= limit * settings["memory_warn_percent"] / 100:
            problems.append("close to its memory limit")

    if not info["token"]:
        problems.append("no BOT_TOKEN in its environment: can't ask Telegram about it")
    else:
        try:
            tg = telegram.check(info["token"])
            row.update(username=tg["username"], pending=tg["pending"])
            if tg["webhook"]:
                problems.append("a webhook is set, so polling gets no messages (left from hosting elsewhere?)")
            elif running and tg["pending"] and is_stuck(conn, bot["name"], at, settings["stuck_after_minutes"]):
                problems.append(f"stuck: messages have waited over {settings['stuck_after_minutes']:g} min")
        except TelegramProblem as problem:
            problems.append(str(problem))

    same_container = previous and previous["container"] == info["id"]
    since = parse(previous["at"]) if same_container else at - timedelta(seconds=settings["check_every_seconds"])
    row["log_errors"], row["last_error"] = scan_errors(docker.logs(bot["id"], since))
    row["problems"] = "\n".join(problems)

    save_check(conn, row)
    alert_changes(conn, row, previous, info, at)
    conn.commit()
    return row


def not_running(info: dict) -> str:
    if info["state"] == "restarting":
        return "keeps crashing: Docker restarts it again and again"
    if info["state"] == "exited":
        return f"not running (stopped, exit code {info['exit_code']})"
    return f"not running ({info['state']})"


def is_stuck(conn, bot: str, at: datetime, minutes: float) -> bool:
    """Have messages been waiting in every check of the last `minutes`?

    The bot picks messages up within seconds while it works, so a check rarely
    sees any waiting; seeing them check after check means it stopped reading.
    """
    last_fine = conn.execute(
        "SELECT max(at) FROM checks WHERE bot = ? AND (pending IS NULL OR pending = 0 OR state != 'running')",
        (bot,)).fetchone()[0]
    first_waiting = conn.execute("SELECT min(at) FROM checks WHERE bot = ? AND at > ?",
                                 (bot, last_fine or "")).fetchone()[0]
    return first_waiting is not None and parse(first_waiting) <= at - timedelta(minutes=minutes)


def save_check(conn, row: dict) -> None:
    columns = ", ".join(row)
    conn.execute(f"INSERT INTO checks ({columns}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def last_check(conn, bot: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM checks WHERE bot = ? ORDER BY at DESC, id DESC LIMIT 1", (bot,)).fetchone()


def add_alert(conn, bot: str, text: str, at: datetime) -> None:
    conn.execute("INSERT INTO alerts (at, bot, text) VALUES (?, ?, ?)", (iso(at), bot, text))


def alert_changes(conn, row: dict, previous, info: dict, at: datetime) -> None:
    """Alerts for what changed since the previous check."""
    name = row["bot"] + (f" (@{row['username']})" if row["username"] else "")
    problems = set(filter(None, row["problems"].split("\n")))
    before = set(filter(None, previous["problems"].split("\n"))) if previous else set()

    if previous is None:
        add_alert(conn, row["bot"], f"👀 Watching a new bot: {name}", at)
    elif previous["container"] == info["id"] and (info["restarts"] or 0) > (previous["restarts"] or 0):
        recent = conn.execute("SELECT 1 FROM alerts WHERE bot = ? AND text LIKE '🔁%' AND at > ?",
                              (row["bot"], iso(at - RESTART_ALERT_EVERY))).fetchone()
        if not recent:
            text = f"🔁 {name} crashed and Docker restarted it ({info['restarts']} times so far)"
            if row["last_error"]:
                text += f"\nLast error: {row['last_error']}"
            add_alert(conn, row["bot"], text, at)

    new = sorted(problems - before)
    if new:
        add_alert(conn, row["bot"], f"🔴 {name}:\n" + "\n".join(f"• {p}" for p in new), at)
    elif before and not problems:
        add_alert(conn, row["bot"], f"🟢 {name} is fine again", at)


def prune(conn, settings: dict, at: datetime | None = None) -> None:
    """Forget old checks, alerts and usage (see keep_*_days in settings.yaml)."""
    at = at or utcnow()
    checks_before = iso(at - timedelta(days=settings["keep_checks_days"]))
    conn.execute("DELETE FROM checks WHERE at < ?", (checks_before,))
    conn.execute("DELETE FROM alerts WHERE at < ?", (checks_before,))
    conn.execute("DELETE FROM events WHERE at < ?", (iso(at - timedelta(days=settings["keep_usage_days"])),))
    conn.commit()


# --- Reading ----------------------------------------------------------------------

def status(conn, at: datetime | None = None) -> list[dict]:
    """Every current bot: its latest check, uptime, errors (and the latest one seen) and usage today."""
    at = at or utcnow()
    newest = conn.execute("SELECT max(at) FROM checks").fetchone()[0]
    if newest is None:
        return []
    rows = conn.execute(
        """SELECT * FROM checks c WHERE at >= ? AND id = (SELECT id FROM checks WHERE bot = c.bot
           ORDER BY at DESC, id DESC LIMIT 1) ORDER BY bot""",
        (iso(parse(newest) - CURRENT),)).fetchall()
    midnight = iso(local_midnight(at))
    result = []
    for row in rows:
        bot = dict(row)
        bot["problems"] = [p for p in bot["problems"].split("\n") if p]
        bot["uptime_day"] = uptime(conn, bot["bot"], at - timedelta(days=1))
        bot["uptime_week"] = uptime(conn, bot["bot"], at - timedelta(days=7))
        error = conn.execute("SELECT at, last_error FROM checks WHERE bot = ? AND last_error IS NOT NULL "
                             "ORDER BY at DESC LIMIT 1", (bot["bot"],)).fetchone()
        bot["last_error"], bot["last_error_at"] = (error["last_error"], error["at"]) if error else (None, None)
        bot["errors_today"] = conn.execute("SELECT coalesce(sum(log_errors), 0) FROM checks WHERE bot = ? AND at >= ?",
                                           (bot["bot"], midnight)).fetchone()[0]
        bot["today"] = usage_totals(events(conn, bot["username"], midnight)) if bot["username"] else None
        result.append(bot)
    return result


def uptime(conn, bot: str, since: datetime) -> float | None:
    """Percent of checks since `since` that found the bot running."""
    share = conn.execute("SELECT avg(state = 'running') FROM checks WHERE bot = ? AND at >= ?",
                         (bot, iso(since))).fetchone()[0]
    return None if share is None else round(share * 100, 1)


def find_bot(conn, name: str) -> tuple[str, str | None]:
    """A bot by its name or @username -> (name, username)."""
    name = name.lstrip("@")
    row = conn.execute("SELECT bot, username FROM checks WHERE bot = ? OR lower(username) = lower(?) "
                       "ORDER BY at DESC LIMIT 1", (name, name)).fetchone()
    if row is None:
        known = [r[0] for r in conn.execute("SELECT DISTINCT bot FROM checks ORDER BY bot")]
        raise NotFound(f"No bot {name!r}. Known: {', '.join(known) or 'none yet'}.")
    return row["bot"], row["username"]


def alerts(conn, after: int | None = None, limit: int = 50) -> list[dict]:
    """Alerts after the one with id `after`, oldest first; without `after`, the latest `limit`."""
    if after is None:
        rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()[::-1]
    else:
        rows = conn.execute("SELECT * FROM alerts WHERE id > ? ORDER BY id LIMIT ?", (after, limit)).fetchall()
    return [dict(r) for r in rows]


# --- Usage ------------------------------------------------------------------------

def save_events(conn, username: str, new_events: list[dict]) -> int:
    conn.executemany(
        "INSERT INTO events (username, at, kind, name, user_id, chat, ms, ok) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(username.lstrip("@"), iso(e["at"]), e["kind"], e.get("name"), e.get("user"), e.get("chat"),
          e.get("ms"), int(e.get("ok", True))) for e in new_events])
    conn.commit()
    return len(new_events)


def events(conn, username: str, since: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM events WHERE username = ? AND at >= ? ORDER BY at",
                        (username, since)).fetchall()


def usage_totals(rows) -> dict:
    timed = [r["ms"] for r in rows if r["ms"] is not None]
    return {
        "updates": len(rows),
        "users": len({r["user_id"] for r in rows if r["user_id"]}),
        "failed": sum(1 for r in rows if not r["ok"]),
        "avg_ms": round(sum(timed) / len(timed)) if timed else None,
    }


def usage(conn, name: str, days: int = 7, at: datetime | None = None) -> dict:
    """How a bot was used in the last `days` days (today included), day by day."""
    if days < 1:
        raise Invalid("days should be 1 or more")
    at = at or utcnow()
    bot, username = find_bot(conn, name)
    first_day = local_midnight(at) - timedelta(days=days - 1)
    rows = events(conn, username, iso(first_day)) if username else []

    by_day = {(first_day + timedelta(days=i)).date().isoformat(): [] for i in range(days)}
    for r in rows:
        day = parse(r["at"]).astimezone(LOCAL_TZ).date().isoformat()
        by_day.setdefault(day, []).append(r)
    users = {r["user_id"] for r in rows if r["user_id"]}
    earlier = {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM events WHERE username = ? AND at < ?",
                                          (username, iso(first_day)))} if username else set()
    commands = Counter(r["name"] for r in rows if r["kind"] == "command")
    kinds = Counter(r["kind"] if r["kind"] != "message" else f"message: {r['name']}" for r in rows
                    if r["kind"] != "command")
    return {
        "bot": bot,
        "username": username,
        "days": [{"date": day, **usage_totals(day_rows)} for day, day_rows in sorted(by_day.items())],
        "total": usage_totals(rows) | {"new_users": len(users - earlier)},
        "commands": commands.most_common(10),
        "other": kinds.most_common(10),
        "blocked": sum(1 for r in rows if r["kind"] == "member" and r["name"] == "kicked"),
    }
