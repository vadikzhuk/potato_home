"""Talks to the botwatch service. The bot never touches its database itself.

botwatch doesn't know people: the bot checks their access ("botwatch" in the users
service) and asks botwatch as a service.
"""

import os

from ..common import ServiceClient


class BotwatchClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(os.environ.get("BOTWATCH_URL", "http://botwatch:8000"), "botwatch", **kwargs)

    async def bots(self) -> list[dict]:
        """Every bot as last checked."""
        return await self.call("GET", "/bots")

    async def usage(self, name: str, days: int = 7) -> dict:
        return await self.call("GET", f"/bots/{name}/usage", params={"days": days})

    async def alerts(self, after: int | None = None, limit: int = 50) -> list[dict]:
        """Alerts after id `after`, oldest first; without it, the latest `limit` ones."""
        params = {"limit": limit} | ({"after": after} if after is not None else {})
        return await self.call("GET", "/alerts", params=params)


api = BotwatchClient()
