"""Things the tests share: fake Docker and Telegram, settings, a database."""

from datetime import datetime, timedelta, timezone

from botwatch import db
from botwatch.telegram import TelegramProblem

SETTINGS = {"check_every_seconds": 60, "stuck_after_minutes": 5, "memory_warn_percent": 90,
            "keep_checks_days": 30, "keep_usage_days": 365}
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def minutes(n: float) -> datetime:
    return T0 + timedelta(minutes=n)


def memory_db():
    return db.connect(":memory:")


class FakeDocker:
    """One container per bot, changed by the tests: docker.containers["quiz"]["state"] = "exited"."""

    def __init__(self, *names: str):
        self.containers = {name: container(name) for name in names}
        self.log_text = {name: "" for name in names}

    def bots(self):
        return [{"name": name, "id": c["id"]} for name, c in sorted(self.containers.items())]

    def _by_id(self, container_id):
        return next(c for c in self.containers.values() if c["id"] == container_id)

    def inspect(self, container_id):
        return dict(self._by_id(container_id))

    def stats(self, container_id):
        c = self._by_id(container_id)
        return {"cpu_percent": 0.5, "memory_mb": c["memory_mb"], "memory_limit_mb": 256.0}

    def logs(self, container_id, since):
        name = next(n for n, c in self.containers.items() if c["id"] == container_id)
        return self.log_text[name]


def container(name: str) -> dict:
    return {"id": f"id-{name}", "state": "running", "exit_code": 0, "started_at": "2026-11-01T10:00:00+00:00",
            "restarts": 0, "health": None, "token": f"123:{name}", "memory_mb": 50.0}


class FakeTelegram:
    def __init__(self):
        self.pending = 0
        self.webhook = None
        self.problem = None  # e.g. "Telegram rejects the token (revoked or mistyped?)"

    def check(self, token):
        if self.problem:
            raise TelegramProblem(self.problem)
        return {"username": token.split(":")[1] + "_bot", "pending": self.pending, "webhook": self.webhook}
