"""Asks Docker about the bot containers, through docker-proxy.

Full access to Docker equals admin rights on the server, so botwatch never gets the
Docker socket itself. docker-proxy (see docker-compose.yml) passes on only requests
that read container information, and refuses everything that changes something.

Docker's API: https://docs.docker.com/reference/api/engine/
"""

import json
import os
import re
import struct
from datetime import datetime

import httpx

BOT_LABEL = "potato.bot"
TOKEN_VARIABLE = "BOT_TOKEN"


class DockerError(Exception):
    """Docker (or docker-proxy) can't be reached or refused."""


class Docker:
    def __init__(self, url: str | None = None, transport: httpx.BaseTransport | None = None):
        self.url = url or os.environ.get("DOCKER_URL") or "http://docker-proxy:2375"
        self.http = httpx.Client(base_url=self.url, timeout=15, transport=transport)  # tests pass a fake transport

    def _get(self, path: str, **params) -> httpx.Response:
        try:
            response = self.http.get(path, params=params)
        except httpx.HTTPError as error:
            raise DockerError(f"Docker isn't reachable at {self.url} ({type(error).__name__})") from None
        if response.is_error:
            raise DockerError(f"Docker answered HTTP {response.status_code} to {path}")
        return response

    def bots(self) -> list[dict]:
        """Every container with the potato.bot label, running or not: [{"name", "id"}]."""
        containers = self._get("/containers/json", all="true",
                               filters=json.dumps({"label": [BOT_LABEL]})).json()
        bots = []
        for c in containers:
            name = c["Labels"].get("com.docker.compose.service") or c["Names"][0].lstrip("/")
            bots.append({"name": name, "id": c["Id"]})
        return sorted(bots, key=lambda b: b["name"])

    def inspect(self, container_id: str) -> dict:
        """What one container is doing now."""
        info = self._get(f"/containers/{container_id}/json").json()
        state = info["State"]
        env = dict(line.split("=", 1) for line in info["Config"]["Env"] or [] if "=" in line)
        return {
            "id": info["Id"],
            "state": state["Status"],  # created, running, restarting, exited, paused, dead
            "exit_code": state.get("ExitCode"),
            "started_at": iso(state.get("StartedAt")),
            "restarts": info.get("RestartCount", 0),
            "health": (state.get("Health") or {}).get("Status"),  # healthy, unhealthy, or None
            "token": env.get(TOKEN_VARIABLE) or None,
        }

    def stats(self, container_id: str) -> dict:
        """Memory and CPU now. Takes about a second: Docker measures CPU over that time."""
        s = self._get(f"/containers/{container_id}/stats", stream="false").json()
        return {"cpu_percent": cpu_percent(s), **memory(s)}

    def logs(self, container_id: str, since: datetime) -> str:
        """What the bot printed since `since` (both stdout and stderr)."""
        raw = self._get(f"/containers/{container_id}/logs", stdout="true", stderr="true",
                        since=int(since.timestamp())).content
        return demultiplex(raw)


def iso(docker_time: str | None) -> str | None:
    """'2026-11-01T18:54:03.123456789Z' -> '2026-11-01T18:54:03+00:00'; Docker's zero time -> None."""
    if not docker_time or docker_time.startswith("0001-"):
        return None
    return docker_time[:19] + "+00:00"


def cpu_percent(stats: dict) -> float:
    """CPU use as `docker stats` shows it: 100% = one full core."""
    cpu, before = stats.get("cpu_stats") or {}, stats.get("precpu_stats") or {}
    try:
        used = cpu["cpu_usage"]["total_usage"] - before["cpu_usage"]["total_usage"]
        total = cpu["system_cpu_usage"] - before["system_cpu_usage"]
    except KeyError:
        return 0.0
    cores = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1])
    if total <= 0 or used < 0:
        return 0.0
    return round(used / total * cores * 100, 1)


def memory(stats: dict) -> dict:
    """Memory in MB as `docker stats` shows it: without the file cache, which the system can free."""
    m = stats.get("memory_stats") or {}
    if "usage" not in m:
        return {"memory_mb": None, "memory_limit_mb": None}
    cache = m.get("stats", {}).get("inactive_file", m.get("stats", {}).get("cache", 0))
    return {"memory_mb": round((m["usage"] - cache) / 2**20, 1),
            "memory_limit_mb": round(m["limit"] / 2**20, 1) if m.get("limit") else None}


def demultiplex(raw: bytes) -> str:
    """Docker sends the logs of a container without a terminal in frames: 8 bytes of header
    (stream number, 3 zero bytes, payload length) before each piece of output."""
    if not raw or raw[0] not in (0, 1, 2) or raw[1:4] != b"\0\0\0":
        return raw.decode(errors="replace")  # a container with a terminal (tty: true) sends plain text
    parts, i = [], 0
    while i + 8 <= len(raw):
        (length,) = struct.unpack(">I", raw[i + 4:i + 8])
        parts.append(raw[i + 8:i + 8 + length])
        i += 8 + length
    return b"".join(parts).decode(errors="replace")


ERROR_LINE = re.compile(r"\b(ERROR|CRITICAL|FATAL)\b")
TRACEBACK = "Traceback (most recent call last)"
CHAINED = ("During handling of the above exception", "The above exception was the direct cause")
# A bot token (123456789:AA...) in a log line: python-telegram-bot prints a rejected one,
# and request URLs contain it. Alerts go out in Telegram, so it's hidden first.
TOKEN = re.compile(r"(?<!\d)\d{5,}:[A-Za-z0-9_-]{10,}")


def scan_errors(text: str) -> tuple[int, str | None]:
    """How many errors a log shows, and the last one.

    An error is a log line with ERROR (or CRITICAL, FATAL), or a Python traceback; a
    traceback right after its ERROR line (as logging prints it) counts once. For a
    traceback, the last error is its final line: the exception, e.g. "ValueError: ...".
    Bot tokens in it are replaced with <token>.
    """
    count, last = 0, None
    counted = False  # the error being printed now is counted already
    in_traceback = False
    for line in text.splitlines():
        if line.startswith(TRACEBACK):
            in_traceback = True
            if not counted:
                count += 1
                counted = True
        elif in_traceback:
            if line.strip() and not line.startswith((" ", "\t")):
                last, in_traceback = line.strip(), False  # the exception itself
        elif line.startswith(CHAINED) or not line.strip():
            pass  # still the same error
        elif ERROR_LINE.search(line):
            count += 1
            last, counted = line.strip(), True
        else:
            counted = False
    return count, TOKEN.sub("<token>", last)[:300] if last else None
