"""What the bot says about users. No Telegram or HTTP calls here."""

from ..common import esc

HELP = """<b>Users</b> (changes need users admin)
/user_list - users and their access
/user_add Anna 123456789 - add a user (Telegram id optional)
/user_link Anna 123456789 - connect a user to a Telegram id
/user_grant Anna tickets write - give access: read, write or admin
/user_revoke Anna tickets - take access away
/user_deactivate Anna, /user_activate Anna"""


def access_text(access: dict[str, str]) -> str:
    """{"tickets": "write", "users": "read"} -> 'tickets: write, users: read'"""
    return ", ".join(f"{service}: {level}" for service, level in access.items()) or "no access"


def user_line(user: dict) -> str:
    tg = "📱" if user["telegram_id"] else "—"
    inactive = " <i>(inactive)</i>" if not user["is_active"] else ""
    return f"{tg} <b>{esc(user['name'])}</b>{inactive}: {access_text(user['access'])}"


def user_list(users: list[dict]) -> str:
    return "\n".join(["<b>Users</b>", ""] + [user_line(u) for u in users] + ["", "📱 = can use this bot"])
