-- Tables of the estate service. Applied on every start; IF NOT EXISTS makes that safe.
-- Times are UTC ISO text. Listings are never deleted: ones that leave the sites
-- just stop being seen (last_seen gets old), so the history stays.

PRAGMA journal_mode = WAL;  -- lets readers and one writer work at the same time

CREATE TABLE IF NOT EXISTS listings (
    id               INTEGER PRIMARY KEY,
    source           TEXT    NOT NULL,  -- 'trovacasa' or 'pvp'
    source_id        TEXT    NOT NULL,  -- the listing's id on that site
    url              TEXT    NOT NULL,
    title            TEXT    NOT NULL,
    kind             TEXT    NOT NULL,  -- apartment, house or other
    is_auction       INTEGER NOT NULL DEFAULT 0,
    region           TEXT    NOT NULL,
    province         TEXT,
    town             TEXT,
    address          TEXT,
    price            REAL,              -- euros, as last seen
    first_price      REAL,              -- euros, as first seen
    m2               REAL,
    rooms            INTEGER,           -- "locali": rooms including the living room
    bedrooms         INTEGER,
    bedrooms_guessed INTEGER NOT NULL DEFAULT 0,  -- 1 = not stated, worked out as rooms - 1
    description      TEXT    NOT NULL DEFAULT '',
    features         TEXT    NOT NULL DEFAULT '',  -- the site's tags, comma separated
    photo            TEXT,
    auction_date     TEXT,              -- YYYY-MM-DD
    occupancy        TEXT,              -- auctions: free, occupied, being freed, or NULL (unknown)
    first_seen       TEXT    NOT NULL,
    last_seen        TEXT    NOT NULL,
    duplicate_of     INTEGER REFERENCES listings (id),  -- the same property, listed again
    hidden           INTEGER NOT NULL DEFAULT 0,  -- someone said "not interesting"
    starred          INTEGER NOT NULL DEFAULT 0,  -- someone is watching it
    UNIQUE (source, source_id)
);

-- Every price a listing ever had, to spot price drops.
CREATE TABLE IF NOT EXISTS prices (
    listing_id INTEGER NOT NULL REFERENCES listings (id),
    price      REAL    NOT NULL,
    seen_at    TEXT    NOT NULL
);

-- One row per fetch of all sources: when, how much was found, what went wrong.
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    seen        INTEGER NOT NULL DEFAULT 0,  -- listings read from the sites
    added       INTEGER NOT NULL DEFAULT 0,  -- of those, new ones
    errors      TEXT    NOT NULL DEFAULT ''  -- one line per source that failed
);
