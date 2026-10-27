import httpx
import pytest

from bot.common import ApiError, ServiceClient, has_level


def client_with(handler) -> ServiceClient:
    return ServiceClient("http://svc", "tickets", token="secret", transport=httpx.MockTransport(handler))


async def test_sends_token_and_acting_person():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(request.headers)
        return httpx.Response(200, json={})

    await client_with(handler).call("POST", "/tickets", 111, json={})
    assert seen["x-api-token"] == "secret" and seen["x-telegram-id"] == "111"


async def test_errors_carry_the_services_message():
    api = client_with(lambda request: httpx.Response(403, json={"detail": "No write access."}))
    with pytest.raises(ApiError, match="No write access") as error:
        await api.call("GET", "/x")
    assert error.value.status == 403


async def test_unreachable_service_names_it():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ApiError, match="tickets service is not reachable"):
        await client_with(handler).call("GET", "/x")


def test_has_level():
    anna = {"is_active": True, "access": {"tickets": "write"}}
    assert has_level(anna, "tickets", "read") and has_level(anna, "tickets", "write")
    assert not has_level(anna, "tickets", "admin")
    assert not has_level(anna, "users", "read")
    assert not has_level({**anna, "is_active": False}, "tickets", "read")
    assert not has_level(None, "tickets", "read")
