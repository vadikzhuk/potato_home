"""Asks Telegram about a bot, with the bot's own token.

  getMe           does Telegram accept the token? And the bot's @username.
  getWebhookInfo  how many messages wait for the bot. A running bot picks them up
                  within seconds; when they pile up, the bot is stuck. It also shows
                  a webhook left over from hosting elsewhere: while one is set,
                  the bot can't get messages by polling.

Neither call takes messages away from the bot (only getUpdates would), so asking
while the bot runs is safe.

Tokens never appear in logs or error messages: they are in the URL of every call.
"""

import httpx

API = "https://api.telegram.org"


class TelegramProblem(Exception):
    """Something to show as the bot's problem."""


class Telegram:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=API, timeout=15, transport=transport)  # tests pass a fake transport

    def _call(self, token: str, method: str) -> dict:
        try:
            response = self.http.get(f"/bot{token}/{method}")
        except httpx.HTTPError:
            raise TelegramProblem("Telegram isn't reachable") from None
        if response.status_code in (401, 404):
            raise TelegramProblem("Telegram rejects the token (revoked or mistyped?)")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not body.get("ok"):
            raise TelegramProblem(f"Telegram answered HTTP {response.status_code}: {body.get('description', '')}")
        return body["result"]

    def check(self, token: str) -> dict:
        """{"username", "pending", "webhook"} for the bot with this token."""
        me = self._call(token, "getMe")
        webhook = self._call(token, "getWebhookInfo")
        return {"username": me["username"], "pending": webhook.get("pending_update_count", 0),
                "webhook": webhook.get("url") or None}
