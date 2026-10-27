"""People as the users service would send them, for tests."""

from tickets.people import People


def user(id, name, tickets=None, telegram_id=None, active=True):
    access = {"tickets": tickets} if tickets else {}
    return {"id": id, "name": name, "telegram_id": telegram_id, "is_active": active,
            "created_at": "2026-10-27T10:00:00+00:00", "access": access}


def make_people(*users) -> People:
    users = list(users)
    return People(load=lambda: users)


def family() -> People:
    """Alex (tickets admin), Anna (write), Kid (read), Bob (no access), Old (inactive writer)."""
    return make_people(
        user(1, "Alex", "admin", telegram_id=111),
        user(2, "Anna", "write", telegram_id=222),
        user(3, "Kid", "read", telegram_id=333),
        user(4, "Bob", telegram_id=444),
        user(5, "Old", "write", active=False),
    )
