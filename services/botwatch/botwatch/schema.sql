-- One row per bot per check (every minute by default)
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY,
    bot TEXT NOT NULL,             -- the compose service name, e.g. digital_gland_bot
    at TEXT NOT NULL,              -- UTC, ISO format
    container TEXT,                -- container id: a new one means the bot was recreated (updated)
    username TEXT,                 -- the bot's @username, from Telegram
    state TEXT NOT NULL,           -- running, restarting, exited, ...
    started_at TEXT,               -- when the container started this time
    restarts INTEGER,              -- restarts after crashes, counted by Docker
    memory_mb REAL,
    memory_limit_mb REAL,
    cpu_percent REAL,
    pending INTEGER,               -- messages Telegram holds for the bot, not picked up yet
    log_errors INTEGER NOT NULL DEFAULT 0,  -- errors in the bot's log since the previous check
    last_error TEXT,
    problems TEXT NOT NULL DEFAULT ''       -- what's wrong, one problem per line; '' = fine
);
CREATE INDEX IF NOT EXISTS checks_bot_at ON checks (bot, at);

-- Messages for the admins: the home bot sends them in Telegram
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    bot TEXT NOT NULL,
    text TEXT NOT NULL
);

-- One row per update a bot handled, sent by botstats.py inside the bot
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,        -- the bot's @username
    at TEXT NOT NULL,              -- UTC, ISO format
    kind TEXT NOT NULL,            -- command, message, button, inline, member, other
    name TEXT,                     -- /start, voice, kicked (= blocked the bot)...
    user_id INTEGER,               -- the Telegram user
    chat TEXT,                     -- private, group, supergroup, channel
    ms INTEGER,                    -- how long the bot took
    ok INTEGER NOT NULL            -- 0: the bot failed on it
);
CREATE INDEX IF NOT EXISTS events_username_at ON events (username, at);
