-- Tables of the users service. Applied on every start; IF NOT EXISTS makes that safe.
-- Times are UTC ISO text. Users are never deleted, only deactivated.

PRAGMA journal_mode = WAL;  -- lets readers and one writer work at the same time

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    telegram_id INTEGER UNIQUE,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);

-- Who may use which service, and how much. No row = no access.
-- Each service decides what the levels mean for it (see its core.py).
CREATE TABLE IF NOT EXISTS access (
    user_id INTEGER NOT NULL REFERENCES users (id),
    service TEXT    NOT NULL,  -- e.g. 'tickets', or 'users' for managing users and access
    level   TEXT    NOT NULL CHECK (level IN ('read', 'write', 'admin')),
    PRIMARY KEY (user_id, service)
);
