import httpx
import pytest

from botwatch.telegram import Telegram, TelegramProblem


def telegram(answer) -> Telegram:
    return Telegram(transport=httpx.MockTransport(answer))


def test_check():
    def answer(request):
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"username": "quiz_bot"}})
        return httpx.Response(200, json={"ok": True, "result": {"url": "", "pending_update_count": 4}})

    assert telegram(answer).check("1:abc") == {"username": "quiz_bot", "pending": 4, "webhook": None}


def test_problems_never_show_the_token():
    rejected = telegram(lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(TelegramProblem, match="rejects the token") as error:
        rejected.check("1:secret")
    assert "secret" not in str(error.value)

    def offline(request):
        raise httpx.ConnectError(f"can't reach {request.url}")

    with pytest.raises(TelegramProblem) as error:
        telegram(offline).check("1:secret")
    assert str(error.value) == "Telegram isn't reachable"
