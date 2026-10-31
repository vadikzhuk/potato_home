from datetime import datetime

import pytest

from estate import core, db, fetcher

from helpers import criteria, listing

CRITERIA = criteria()


class FakeSource:
    def __init__(self, *listings, fail=False):
        self.listings, self.fail = listings, fail

    def fetch(self, search, http, pause):
        yield from self.listings
        if self.fail:
            raise RuntimeError("site is down")


@pytest.fixture
def conn():
    return db.connect(":memory:")


def test_a_broken_source_does_not_stop_the_others(conn):
    sources = {"good": FakeSource(listing(), listing()), "bad": FakeSource(listing(), fail=True)}
    run = fetcher.run(conn, CRITERIA, sources, say=lambda text: None)
    assert (run["seen"], run["added"]) == (3, 3)
    assert run["errors"] == "bad: RuntimeError: site is down"
    assert run["finished_at"]


def test_running_again_finds_nothing_new(conn):
    same = listing()
    fetcher.run(conn, CRITERIA, {"s": FakeSource(same)}, say=lambda text: None)
    assert fetcher.run(conn, CRITERIA, {"s": FakeSource(same)}, say=lambda text: None)["added"] == 0


def test_is_due(conn):
    at = lambda text: datetime.fromisoformat(text).astimezone(core.LOCAL_TZ)  # noqa: E731
    morning = datetime(2026, 10, 31, 4, 0, tzinfo=core.LOCAL_TZ)
    later = datetime(2026, 10, 31, 6, 0, tzinfo=core.LOCAL_TZ)
    assert not fetcher.is_due(conn, CRITERIA, morning)   # before 05:00
    assert fetcher.is_due(conn, CRITERIA, later)          # never fetched
    conn.execute("INSERT INTO runs (started_at) VALUES (?)", (later.isoformat(),))
    assert not fetcher.is_due(conn, CRITERIA, later)      # already today
    assert fetcher.is_due(conn, CRITERIA, at("2026-11-01T06:00:00+01:00"))  # next day


def test_one_fetch_at_a_time_even_from_another_program(conn):
    conn.execute("INSERT INTO runs (started_at) VALUES ('2026-10-31T09:44:00+00:00')")  # still running
    with pytest.raises(fetcher.Busy, match="#1 is already running"):
        fetcher.run(conn, CRITERIA, {"s": FakeSource(listing())}, say=lambda text: None)


def test_a_fetch_cut_off_by_a_restart_is_tried_again(conn):
    later = datetime(2026, 10, 31, 6, 0, tzinfo=core.LOCAL_TZ)
    conn.execute("INSERT INTO runs (started_at) VALUES (?)", (later.isoformat(),))
    assert not fetcher.is_due(conn, CRITERIA, later)   # running
    assert core.mark_interrupted(conn) == 1           # the service restarted
    assert core.running_run(conn) is None and core.latest_run(conn) is None
    assert fetcher.is_due(conn, CRITERIA, later)       # so today's fetch runs again
