import json
import struct
from datetime import datetime, timezone

import httpx
import pytest

from botwatch.docker import Docker, DockerError, cpu_percent, demultiplex, iso, memory, scan_errors


def frame(stream: int, text: str) -> bytes:
    data = text.encode()
    return bytes([stream, 0, 0, 0]) + struct.pack(">I", len(data)) + data


def test_demultiplex():
    assert demultiplex(frame(1, "hello\n") + frame(2, "oops\n")) == "hello\noops\n"
    assert demultiplex(b"plain text\n") == "plain text\n"  # tty: true
    assert demultiplex(b"") == ""


def test_scan_errors_counts_a_logged_traceback_once():
    log = """2026-11-01 INFO bot started
2026-11-01 ERROR telegram.ext.Application: No error handlers are registered, logging exception.
Traceback (most recent call last):
  File "/app/bot.py", line 3, in handler
    int(text)
ValueError: invalid literal for int() with base 10: 'hi'
2026-11-01 INFO still running
Traceback (most recent call last):
  File "/app/bot.py", line 9, in main
KeyError: 'x'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/app/bot.py", line 10, in main
RuntimeError: worse
"""
    assert scan_errors(log) == (2, "RuntimeError: worse")
    assert scan_errors("all fine\n") == (0, None)
    assert scan_errors("ERROR GET https://api.telegram.org/bot123456789:AAEsyb-x_Y1234567/getMe failed") == (
        1, "ERROR GET https://api.telegram.org/bot<token>/getMe failed")
    assert scan_errors("2026 | ERROR | x | boom") == (1, "2026 | ERROR | x | boom")


def test_numbers():
    assert iso("2026-11-01T18:54:03.123456789Z") == "2026-11-01T18:54:03+00:00"
    assert iso("0001-01-01T00:00:00Z") is None
    stats = {"cpu_stats": {"cpu_usage": {"total_usage": 300}, "system_cpu_usage": 2000, "online_cpus": 4},
             "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
             "memory_stats": {"usage": 60 * 2**20, "limit": 256 * 2**20, "stats": {"inactive_file": 10 * 2**20}}}
    assert cpu_percent(stats) == 80.0
    assert memory(stats) == {"memory_mb": 50.0, "memory_limit_mb": 256.0}
    assert cpu_percent({}) == 0.0 and memory({})["memory_mb"] is None  # a stopped container


def test_api_calls():
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path == "/containers/json":
            return httpx.Response(200, json=[
                {"Id": "b", "Names": ["/potato_home-zeta-1"], "Labels": {"com.docker.compose.service": "zeta"}},
                {"Id": "a", "Names": ["/alpha"], "Labels": {"potato.bot": "true"}}])
        if request.url.path == "/containers/a/json":
            return httpx.Response(200, json={
                "Id": "a", "RestartCount": 2, "Config": {"Env": ["BOT_TOKEN=1:abc", "PATH=/usr/bin"]},
                "State": {"Status": "running", "ExitCode": 0, "StartedAt": "2026-11-01T10:00:00.5Z"}})
        if request.url.path == "/containers/a/logs":
            return httpx.Response(200, content=frame(1, "line\n"))
        return httpx.Response(404, json={"message": "no such container"})

    docker = Docker("http://proxy", transport=httpx.MockTransport(answer))
    assert docker.bots() == [{"name": "alpha", "id": "a"}, {"name": "zeta", "id": "b"}]
    assert json.loads(seen[0].params["filters"]) == {"label": ["potato.bot"]}
    assert docker.inspect("a") == {"id": "a", "state": "running", "exit_code": 0,
                                   "started_at": "2026-11-01T10:00:00+00:00", "restarts": 2,
                                   "health": None, "token": "1:abc"}
    since = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert docker.logs("a", since) == "line\n"
    assert seen[-1].params["since"] == str(int(since.timestamp()))
    with pytest.raises(DockerError, match="HTTP 404"):
        docker.inspect("gone")
