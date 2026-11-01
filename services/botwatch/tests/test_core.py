import pytest

from botwatch import core

from helpers import SETTINGS, FakeDocker, FakeTelegram, memory_db, minutes


@pytest.fixture
def world():
    return memory_db(), FakeDocker("quiz"), FakeTelegram()


def check(world, at_minute: float):
    conn, docker, telegram = world
    return core.check_all(conn, docker, telegram, SETTINGS, minutes(at_minute))


def alert_texts(conn) -> list[str]:
    return [a["text"] for a in core.alerts(conn)]


def test_a_healthy_bot(world):
    conn = world[0]
    [row] = check(world, 0)
    assert row["state"] == "running" and row["problems"] == "" and row["username"] == "quiz_bot"
    assert alert_texts(conn) == ["👀 Watching a new bot: quiz (@quiz_bot)"]
    check(world, 1)
    assert len(alert_texts(conn)) == 1  # nothing new to say


def test_problem_appears_and_goes_away(world):
    conn, docker, telegram = world
    check(world, 0)
    docker.containers["quiz"].update(state="exited", exit_code=1)
    check(world, 1)
    check(world, 2)  # the same problem again: no second alert
    docker.containers["quiz"].update(state="running")
    check(world, 3)
    assert alert_texts(conn)[1:] == ["🔴 quiz (@quiz_bot):\n• not running (stopped, exit code 1)",
                                     "🟢 quiz (@quiz_bot) is fine again"]


def test_stuck_only_after_messages_wait_long_enough(world):
    conn, docker, telegram = world
    check(world, 0)
    telegram.pending = 3
    for minute in range(1, 7):
        [row] = check(world, minute)
        assert ("stuck" in row["problems"]) == (minute >= 6), minute  # waiting since minute 1, 5 min later
    telegram.pending = 0
    [row] = check(world, 7)
    assert row["problems"] == ""


def test_a_moment_of_waiting_is_not_stuck(world):
    conn, docker, telegram = world
    for minute in range(10):
        telegram.pending = minute % 2  # waiting now and then: the bot picks them up
        [row] = check(world, minute)
        assert row["problems"] == ""


def test_crash_restarts_alert_once_an_hour(world):
    conn, docker, telegram = world
    docker.log_text["quiz"] = "ERROR boom\nTraceback (most recent call last):\n  File x\nValueError: bad\n"
    check(world, 0)
    for minute in (1, 2, 70):
        docker.containers["quiz"]["restarts"] += 1
        check(world, minute)
    restarts = [t for t in alert_texts(conn) if t.startswith("🔁")]
    assert restarts == ["🔁 quiz (@quiz_bot) crashed and Docker restarted it (1 times so far)\nLast error: ValueError: bad",
                        "🔁 quiz (@quiz_bot) crashed and Docker restarted it (3 times so far)\nLast error: ValueError: bad"]


def test_new_container_is_not_a_crash(world):
    conn, docker, telegram = world
    check(world, 0)
    docker.containers["quiz"].update(id="id-new", restarts=0)  # docker compose up -d after an update
    check(world, 1)
    assert not any(t.startswith("🔁") for t in alert_texts(conn))


@pytest.mark.parametrize("change, problem", [
    (lambda d, t: t.__setattr__("problem", "Telegram rejects the token (revoked or mistyped?)"), "rejects the token"),
    (lambda d, t: t.__setattr__("webhook", "https://old.example/hook"), "a webhook is set"),
    (lambda d, t: d.containers["quiz"].update(token=None), "no BOT_TOKEN"),
    (lambda d, t: d.containers["quiz"].update(memory_mb=250.0), "close to its memory limit"),
    (lambda d, t: d.containers["quiz"].update(state="restarting"), "keeps crashing"),
    (lambda d, t: d.containers["quiz"].update(health="unhealthy"), "healthcheck fails"),
])
def test_problems(world, change, problem):
    conn, docker, telegram = world
    change(docker, telegram)
    [row] = check(world, 0)
    assert problem in row["problems"]


def test_status_uptime_and_errors(world):
    conn, docker, telegram = world
    docker.log_text["quiz"] = "2026-11-01 ERROR telegram.ext: oops\n"
    for minute in range(3):
        check(world, minute)
    docker.containers["quiz"]["state"] = "exited"
    docker.log_text["quiz"] = ""
    check(world, 3)
    [bot] = core.status(conn, minutes(4))
    assert bot["uptime_day"] == 75.0 and bot["errors_today"] == 3
    assert bot["problems"] == ["not running (stopped, exit code 0)"]
    assert bot["last_error"] == "2026-11-01 ERROR telegram.ext: oops"  # from an earlier check
    assert bot["last_error_at"] == "2026-11-01T12:02:00+00:00"


def test_removed_bot_leaves_the_status(world):
    conn, docker, telegram = world
    docker.containers["old"] = {**docker.containers["quiz"], "id": "id-old", "token": "1:old"}
    docker.log_text["old"] = ""
    check(world, 0)
    del docker.containers["old"]
    check(world, 20)
    assert [b["bot"] for b in core.status(conn, minutes(20))] == ["quiz"]


def test_usage(world):
    conn = world[0]
    check(world, 0)
    event = {"kind": "command", "name": "/start", "user": 1, "chat": "private", "ms": 100, "ok": True}
    core.save_events(conn, "quiz_bot", [
        {**event, "at": minutes(-60 * 24 * 3)},                       # 3 days ago: user 1 isn't new
        {**event, "at": minutes(0)},
        {**event, "at": minutes(1), "user": 2, "name": "/challenge", "ms": 300},
        {**event, "at": minutes(2), "user": 2, "kind": "message", "name": "voice", "ok": False},
        {**event, "at": minutes(3), "user": 2, "kind": "member", "name": "kicked"},
    ])
    u = core.usage(conn, "@quiz_bot", days=2, at=minutes(5))
    assert u["bot"] == "quiz" and [d["updates"] for d in u["days"]] == [0, 4]
    assert u["total"] == {"updates": 4, "users": 2, "failed": 1, "avg_ms": 150, "new_users": 1}
    assert u["commands"] == [("/start", 1), ("/challenge", 1)]
    assert u["other"] == [("message: voice", 1), ("member", 1)]
    assert u["blocked"] == 1
    assert core.status(conn, minutes(5))[0]["today"]["updates"] == 4
    with pytest.raises(core.NotFound):
        core.usage(conn, "nobody")


def test_prune(world):
    conn = world[0]
    check(world, 0)
    core.save_events(conn, "quiz_bot", [{"at": minutes(0), "kind": "other"}])
    core.prune(conn, SETTINGS, minutes(60 * 24 * 31))
    assert conn.execute("SELECT count(*) FROM checks").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1  # usage is kept a year
