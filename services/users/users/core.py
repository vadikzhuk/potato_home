"""Business logic of the users service: people and their access to every service.

Every other service asks this one "who is this?" and "what may they do here?".

Access is one level per user and service. Each level includes the ones before it:
  read  < write < admin
What a level means is up to each service. For this service ("users"):
  read  - see the list of users
  admin - add, change and deactivate users, grant and revoke access
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

LEVELS = ("read", "write", "admin")
USERS = "users"  # this service's own name in the access table
USER_FIELDS = ("name", "telegram_id", "is_active")


class UsersError(Exception):
    """An error with a message meant for the person using the service."""


class NotFound(UsersError):
    pass


class Forbidden(UsersError):
    pass


class Invalid(UsersError):
    pass


@dataclass
class User:
    id: int
    name: str
    telegram_id: int | None
    is_active: bool
    created_at: str
    access: dict[str, str]  # service -> level, e.g. {"tickets": "write"}


def has_level(user: User | None, service: str, needed: str) -> bool:
    """Is this an active user with at least the `needed` level for `service`?"""
    if user is None or not user.is_active or service not in user.access:
        return False
    return LEVELS.index(user.access[service]) >= LEVELS.index(needed)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Reading ------------------------------------------------------------------

def _user(conn: sqlite3.Connection, row: sqlite3.Row) -> User:
    access = dict(conn.execute("SELECT service, level FROM access WHERE user_id = ? ORDER BY service",
                               (row["id"],)).fetchall())
    return User(**{**dict(row), "is_active": bool(row["is_active"]), "access": access})


def count_users(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users(conn: sqlite3.Connection, include_inactive: bool = False) -> list[User]:
    sql = "SELECT * FROM users" + ("" if include_inactive else " WHERE is_active = 1")
    return [_user(conn, row) for row in conn.execute(sql + " ORDER BY name").fetchall()]


def get_user(conn: sqlite3.Connection, user_id: int) -> User:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise NotFound(f"User #{user_id} not found.")
    return _user(conn, row)


def get_user_by_name(conn: sqlite3.Connection, name: str) -> User:
    row = conn.execute("SELECT * FROM users WHERE name = ?", (name.strip(),)).fetchone()
    if row is None:
        raise NotFound(f"User {name!r} not found.")
    return _user(conn, row)


def get_user_by_telegram(conn: sqlite3.Connection, telegram_id: int) -> User:
    row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if row is None:
        raise NotFound(f"No user with Telegram id {telegram_id}.")
    return _user(conn, row)


def first_admin(conn: sqlite3.Connection) -> User | None:
    """The oldest active users admin: who the terminal acts as by default."""
    row = conn.execute(
        "SELECT u.* FROM users u JOIN access a ON a.user_id = u.id"
        " WHERE a.service = ? AND a.level = 'admin' AND u.is_active = 1 ORDER BY u.id LIMIT 1",
        (USERS,),
    ).fetchone()
    return _user(conn, row) if row else None


# --- Changing users -----------------------------------------------------------

def add_user(conn: sqlite3.Connection, actor: User | None, name: str,
             telegram_id: int | None = None) -> User:
    """Create a user without any access. The very first user needs no actor
    and becomes users admin, so somebody can manage everyone else."""
    first = count_users(conn) == 0
    if not first:
        _require_admin(actor)
    user_id = _insert_user(conn, name, telegram_id)
    if first:
        _set_access(conn, user_id, USERS, "admin")
    conn.commit()
    return get_user(conn, user_id)


def update_user(conn: sqlite3.Connection, actor: User, user_id: int, **changes) -> User:
    """Change some of: name, telegram_id, is_active."""
    _require_admin(actor)
    unknown = set(changes) - set(USER_FIELDS)
    if unknown:
        raise Invalid(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    user = get_user(conn, user_id)
    if "name" in changes:
        changes["name"] = _clean_name(changes["name"])
    if changes.get("is_active") is False:
        _protect_last_admin(conn, user)

    try:
        with conn:  # commits at the end, or rolls back on error
            for field, value in changes.items():
                # `field` is safe in the SQL: only names from USER_FIELDS get here
                conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, user_id))
    except sqlite3.IntegrityError:
        raise Invalid("That name or Telegram id is already used by another user.") from None
    return get_user(conn, user_id)


# --- Access -------------------------------------------------------------------

def grant(conn: sqlite3.Connection, actor: User, user_id: int, service: str, level: str) -> User:
    """Give a user `level` access to `service` (replacing any level they had)."""
    _require_admin(actor)
    user = get_user(conn, user_id)
    _check_service(service)
    if level not in LEVELS:
        raise Invalid(f"Level must be one of: {', '.join(LEVELS)}.")
    if service == USERS and level != "admin":
        _protect_last_admin(conn, user)
    _set_access(conn, user_id, service, level)
    conn.commit()
    return get_user(conn, user_id)


def revoke(conn: sqlite3.Connection, actor: User, user_id: int, service: str) -> User:
    """Take away a user's access to `service`."""
    _require_admin(actor)
    user = get_user(conn, user_id)
    if service == USERS:
        _protect_last_admin(conn, user)
    with conn:
        conn.execute("DELETE FROM access WHERE user_id = ? AND service = ?", (user_id, service))
    return get_user(conn, user_id)


def _set_access(conn: sqlite3.Connection, user_id: int, service: str, level: str) -> None:
    conn.execute(
        "INSERT INTO access (user_id, service, level) VALUES (?, ?, ?)"
        " ON CONFLICT (user_id, service) DO UPDATE SET level = excluded.level",
        (user_id, service, level),
    )


# --- users.yaml: seed, export, import -------------------------------------------
# Format of one record:
#   {"name": "Anna", "telegram_id": 123, "active": true, "access": {"tickets": "write"}}

def seed_users(conn: sqlite3.Connection, records: list[dict]) -> None:
    """Create the first users from users.yaml. Only allowed on an empty database."""
    if count_users(conn) > 0:
        raise Invalid("Users already exist; use import instead.")
    for record in records:
        user_id = _insert_user(conn, record.get("name", ""), record.get("telegram_id"))
        if not record.get("active", True):
            conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        for service, level in (record.get("access") or {}).items():
            _check_service(service)
            _set_access(conn, user_id, service, level)
    conn.commit()


def export_users(conn: sqlite3.Connection) -> list[dict]:
    return [
        {"name": u.name, "telegram_id": u.telegram_id, "active": u.is_active, "access": u.access}
        for u in list_users(conn, include_inactive=True)
    ]


def import_users(conn: sqlite3.Connection, actor: User, records: list[dict]) -> list[str]:
    """Make users match the records. Returns what was changed.

    Users missing from the records are left untouched. A record without "access"
    keeps that user's access as it is. Runs in two passes, additions first, so that
    moving the admin role from one person to another works.
    """
    _require_admin(actor)
    changes_made = []
    removals = []  # (user, record) to apply in the second pass

    for record in records:
        name = _clean_name(record.get("name", ""))
        try:
            user = get_user_by_name(conn, name)
        except NotFound:
            user = add_user(conn, actor, name, record.get("telegram_id"))
            changes_made.append(f"added {name}")
        if "telegram_id" in record and record["telegram_id"] != user.telegram_id:
            update_user(conn, actor, user.id, telegram_id=record["telegram_id"])
            changes_made.append(f"{name}: telegram_id")
        if record.get("active", True) and not user.is_active:
            update_user(conn, actor, user.id, is_active=True)
            changes_made.append(f"{name}: activated")
        for service, level in (record.get("access") or {}).items():
            if user.access.get(service) != level:
                grant(conn, actor, user.id, service, level)
                changes_made.append(f"{name}: {service} {level}")
        removals.append((user, record))

    for user, record in removals:
        if "access" in record:
            for service in set(user.access) - set(record["access"] or {}):
                revoke(conn, actor, user.id, service)
                changes_made.append(f"{user.name}: {service} revoked")
        if not record.get("active", True) and user.is_active:
            update_user(conn, actor, user.id, is_active=False)
            changes_made.append(f"{user.name}: deactivated")
    return changes_made


# --- Checks -------------------------------------------------------------------

def _insert_user(conn: sqlite3.Connection, name: str, telegram_id: int | None) -> int:
    name = _clean_name(name)
    try:
        cur = conn.execute("INSERT INTO users (name, telegram_id, created_at) VALUES (?, ?, ?)",
                           (name, telegram_id, now()))
    except sqlite3.IntegrityError:
        conn.rollback()
        raise Invalid(f"User {name!r} or Telegram id {telegram_id} already exists.") from None
    return cur.lastrowid


def _require_admin(actor: User | None) -> None:
    if actor is None or not actor.is_active:
        raise Forbidden("No active user to act as.")
    if not has_level(actor, USERS, "admin"):
        raise Forbidden("Only users admins can manage users and access.")


def _protect_last_admin(conn: sqlite3.Connection, user: User) -> None:
    """Refuse to remove the last active users admin: nobody could manage users anymore."""
    if not has_level(user, USERS, "admin"):
        return
    admins = conn.execute(
        "SELECT COUNT(*) FROM access a JOIN users u ON u.id = a.user_id"
        " WHERE a.service = ? AND a.level = 'admin' AND u.is_active = 1",
        (USERS,),
    ).fetchone()[0]
    if admins == 1:
        raise Invalid(f"{user.name} is the last users admin and must stay one.")


def _check_service(service: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", service or ""):
        raise Invalid(f"Bad service name {service!r}: use lowercase letters, digits and _.")


def _clean_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name:
        raise Invalid("Name can't be empty.")
    return name
