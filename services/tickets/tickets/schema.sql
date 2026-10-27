-- Tables of the tickets service. Applied on every start; IF NOT EXISTS makes that safe.
-- Times are UTC ISO text ('2026-10-27T09:15:00+00:00'), due dates are 'YYYY-MM-DD'.
-- Nothing is ever deleted: tickets get cancelled.
-- creator_id, assignee_id and actor_id are user ids from the users service.

PRAGMA journal_mode = WAL;  -- lets readers and one writer work at the same time

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'done', 'cancelled')),
    creator_id  INTEGER NOT NULL,
    assignee_id INTEGER,
    due_date    TEXT,
    created_at  TEXT    NOT NULL,
    resolved_at TEXT    -- set when the ticket becomes done or cancelled
);

-- One row per change: this is the "picture of the past".
-- For assignee changes, old/new values are names, so history stays readable.
CREATE TABLE IF NOT EXISTS ticket_events (
    id        INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets (id),
    actor_id  INTEGER,
    at        TEXT    NOT NULL,
    action    TEXT    NOT NULL,  -- created, title, description, due_date, assignee, status
    old_value TEXT,
    new_value TEXT
);
