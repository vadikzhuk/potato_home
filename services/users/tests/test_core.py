import pytest

from users import core, db


@pytest.fixture
def conn():
    return db.connect(":memory:")


@pytest.fixture
def admin(conn):
    return core.add_user(conn, None, "Alex", telegram_id=111)


@pytest.fixture
def anna(conn, admin):
    return core.add_user(conn, admin, "Anna", telegram_id=222)


def test_first_user_becomes_users_admin(admin):
    assert admin.access == {"users": "admin"}


def test_later_users_need_an_admin_and_start_without_access(conn, admin, anna):
    assert anna.access == {}
    with pytest.raises(core.Forbidden):
        core.add_user(conn, None, "Intruder")
    with pytest.raises(core.Forbidden):
        core.add_user(conn, anna, "Bob")


def test_grant_and_revoke(conn, admin, anna):
    anna = core.grant(conn, admin, anna.id, "tickets", "write")
    assert anna.access == {"tickets": "write"}
    anna = core.grant(conn, admin, anna.id, "tickets", "read")  # replaces the level
    assert anna.access == {"tickets": "read"}
    assert core.revoke(conn, admin, anna.id, "tickets").access == {}


def test_levels_include_lower_ones(conn, admin, anna):
    anna = core.grant(conn, admin, anna.id, "tickets", "write")
    assert core.has_level(anna, "tickets", "read")
    assert core.has_level(anna, "tickets", "write")
    assert not core.has_level(anna, "tickets", "admin")
    assert not core.has_level(anna, "screen", "read")
    anna = core.update_user(conn, admin, anna.id, is_active=False)
    assert not core.has_level(anna, "tickets", "read")


def test_bad_level_or_service(conn, admin, anna):
    with pytest.raises(core.Invalid):
        core.grant(conn, admin, anna.id, "tickets", "owner")
    with pytest.raises(core.Invalid):
        core.grant(conn, admin, anna.id, "Tickets!", "read")


def test_members_cannot_grant(conn, admin, anna):
    with pytest.raises(core.Forbidden):
        core.grant(conn, anna, anna.id, "users", "admin")


def test_last_users_admin_is_protected(conn, admin, anna):
    with pytest.raises(core.Invalid):
        core.revoke(conn, admin, admin.id, "users")
    with pytest.raises(core.Invalid):
        core.grant(conn, admin, admin.id, "users", "read")
    with pytest.raises(core.Invalid):
        core.update_user(conn, admin, admin.id, is_active=False)
    core.grant(conn, admin, anna.id, "users", "admin")
    assert core.revoke(conn, admin, admin.id, "users").access == {}  # Anna is admin now


def test_lookups(conn, admin, anna):
    assert core.get_user_by_name(conn, "anna").id == anna.id
    assert core.get_user_by_telegram(conn, 222).id == anna.id
    assert core.first_admin(conn).id == admin.id
    with pytest.raises(core.NotFound):
        core.get_user_by_telegram(conn, 999)


def test_import_moves_admin_and_syncs_access(conn, admin, anna):
    changes = core.import_users(conn, admin, [
        {"name": "Anna", "access": {"users": "admin", "tickets": "write"}},
        {"name": "Alex", "access": {"tickets": "read"}},   # gives up users admin
        {"name": "Bob", "telegram_id": 333, "active": False},
    ])
    assert changes == ["Anna: users admin", "Anna: tickets write", "Alex: tickets read",
                       "added Bob", "Alex: users revoked", "Bob: deactivated"]
    assert core.get_user_by_name(conn, "Alex").access == {"tickets": "read"}
    assert core.get_user_by_name(conn, "Anna").access == {"tickets": "write", "users": "admin"}
    anna = core.get_user_by_name(conn, "Anna")
    assert core.import_users(conn, anna, core.export_users(conn)) == []


def test_seed(conn):
    core.seed_users(conn, [{"name": "Alex", "access": {"users": "admin", "tickets": "admin"}},
                           {"name": "Anna", "telegram_id": 222, "access": {"tickets": "write"}}])
    assert core.get_user_by_name(conn, "Anna").access == {"tickets": "write"}
    with pytest.raises(core.Invalid):
        core.seed_users(conn, [{"name": "Bob"}])
