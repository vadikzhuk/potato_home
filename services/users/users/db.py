"""Opening the SQLite database and filling it with the first users."""

import os
import sqlite3
from pathlib import Path

import yaml

from . import core

SCHEMA = Path(__file__).with_name("schema.sql")
SERVICE_DIR = Path(__file__).resolve().parent.parent  # services/users when run from the repo


def db_path() -> str:
    """USERS_DB from the environment, or potato_home/data/users/users.db when developing locally."""
    return os.environ.get("USERS_DB") or str(SERVICE_DIR.parent.parent / "data" / "users" / "users.db")


def seed_path() -> Path:
    return Path(os.environ.get("USERS_SEED") or SERVICE_DIR / "users.yaml")


def connect(path: str | None = None, read_only: bool = False) -> sqlite3.Connection:
    """Open the database (creating tables if needed). Use ':memory:' for tests.

    read_only: for the terminal, which only reads; changes go through the service.
    """
    path = path or db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the API may open the connection in one thread and use it in another.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text())
    if read_only:
        conn.execute("PRAGMA query_only = ON")  # any write now fails instead of risking the file
    return conn


def read_users_file(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("users") or []


def write_users_file(path: Path, users: list[dict]) -> None:
    header = (
        "# Users and their access to each service (levels: read, write, admin).\n"
        "# On the very first start (empty database) these users are created.\n"
        "# Later: edit this file and run `users import` to apply it,\n"
        "# or `users export` to write the current users back here.\n"
    )
    path.write_text(header + yaml.safe_dump({"users": users}, sort_keys=False, allow_unicode=True))


def seed_users(conn: sqlite3.Connection) -> None:
    """On the very first start, create the users listed in users.yaml."""
    path = seed_path()
    if path.exists() and core.count_users(conn) == 0:
        core.seed_users(conn, read_users_file(path))
