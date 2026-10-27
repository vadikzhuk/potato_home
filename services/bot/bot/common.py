"""Pieces every part of the bot uses: calling services, time, formatting, replying."""

import html
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from telegram import Update
from telegram.constants import ParseMode

HTML = ParseMode.HTML
LOCAL_TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Riga")
LEVELS = ("read", "write", "admin")  # access levels, each includes the ones before it


class ApiError(Exception):
    """A service said no; `str(error)` is its message for the user."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class ServiceClient:
    """Base for talking to one of our services over HTTP.

    Calls made for a person send their Telegram id, so the service checks
    their access and records them in its history.
    """

    def __init__(self, base_url: str, name: str, token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.name = name
        self.http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Api-Token": token if token is not None else os.environ.get("API_TOKEN", "")},
            timeout=10,
            transport=transport,  # tests pass a fake one
        )

    async def call(self, method: str, path: str, telegram_id: int | None = None, **kwargs):
        headers = {"X-Telegram-Id": str(telegram_id)} if telegram_id else {}
        try:
            response = await self.http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise ApiError(f"The {self.name} service is not reachable ({type(error).__name__}).", 503) from None
        if response.is_error:
            try:
                message = response.json()["detail"]
            except (ValueError, KeyError):
                message = response.text
            raise ApiError(str(message), response.status_code)
        return response.json()


def has_level(user: dict | None, service: str, needed: str) -> bool:
    """Does this user (as the users service sends it) have at least `needed` access to `service`?"""
    if not user or not user["is_active"] or service not in user["access"]:
        return False
    return LEVELS.index(user["access"][service]) >= LEVELS.index(needed)


def esc(text) -> str:
    """Escape text typed by people before putting it into an HTML message."""
    return html.escape(str(text))


def today() -> date:
    return datetime.now(LOCAL_TZ).date()


def local_time(iso: str | None) -> str:
    """'2026-10-27T10:03:00+00:00' -> '27.10 12:03' in home time."""
    if not iso:
        return ""
    return datetime.fromisoformat(iso).astimezone(LOCAL_TZ).strftime("%d.%m %H:%M")


async def reply(update: Update, text: str, **kwargs) -> None:
    await update.effective_message.reply_text(text, parse_mode=HTML, **kwargs)
