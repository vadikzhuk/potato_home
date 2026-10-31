"""Opening the SQLite database."""

import os
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")
SERVICE_DIR = Path(__file__).resolve().parent.parent  # services/estate when run from the repo


def db_path() -> str:
    """ESTATE_DB from the environment, or potato_home/data/estate/estate.db when developing locally."""
    return os.environ.get("ESTATE_DB") or str(SERVICE_DIR.parent.parent / "data" / "estate" / "estate.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open the database (creating tables if needed). Use ':memory:' for tests."""
    path = path or db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the API may open the connection in one thread and use it in another.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["title"]
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text())
    return conn
