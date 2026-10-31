"""Talks to the estate service. The bot never touches its database itself.

Calls made for a person send their Telegram id: the estate service checks their access.
"""

import os

from ..common import ServiceClient


class EstateClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(os.environ.get("ESTATE_URL", "http://estate:8000"), "estate", **kwargs)

    async def top(self, telegram_id: int, limit: int = 10, auctions: bool | None = None) -> list[dict]:
        """The best listings; auctions: True = only auctions, False = none, None = all."""
        params = {"limit": limit} | ({"auctions": auctions} if auctions is not None else {})
        return await self.call("GET", "/listings/top", telegram_id, params=params)

    async def starred(self, telegram_id: int) -> list[dict]:
        return await self.call("GET", "/listings/starred", telegram_id)

    async def listing(self, telegram_id: int, listing_id: int) -> dict:
        return await self.call("GET", f"/listings/{listing_id}", telegram_id)

    async def update(self, telegram_id: int, listing_id: int, **changes) -> dict:
        """Hide or star: update(..., starred=True)"""
        return await self.call("PATCH", f"/listings/{listing_id}", telegram_id, json=changes)

    # Used by the daily digest: the bot asks as a service, not for one person

    async def runs(self, limit: int = 3) -> list[dict]:
        """The latest fetches, newest first (the first may still be running)."""
        return await self.call("GET", "/runs", params={"limit": limit})

    async def digest(self, after_run: int | None = None) -> dict:
        params = {"after_run": after_run} if after_run is not None else {}
        return await self.call("GET", "/digest", params=params)


api = EstateClient()
