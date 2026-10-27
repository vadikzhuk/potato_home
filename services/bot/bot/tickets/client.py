"""Talks to the tickets service. The bot never touches its database itself.

Calls made for a person send their Telegram id: the tickets service checks
their access and records them in the ticket history.
"""

import os

from ..common import ServiceClient


class TicketsClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(os.environ.get("TICKETS_URL", "http://tickets:8000"), "tickets", **kwargs)

    async def tickets(self, telegram_id: int, assignee_id: int | None = None,
                      all_statuses: bool = False) -> list[dict]:
        params = {"status": "all"} if all_statuses else {}
        if assignee_id is not None:
            params["assignee_id"] = assignee_id
        return await self.call("GET", "/tickets", telegram_id, params=params)

    async def ticket(self, telegram_id: int, ticket_id: int) -> dict:
        """{"ticket": {...}, "history": [...]}"""
        return await self.call("GET", f"/tickets/{ticket_id}", telegram_id)

    async def create_ticket(self, telegram_id: int, title: str, description: str = "",
                            due_date: str | None = None, assignee_id: int | None = None) -> dict:
        body = {"title": title, "description": description, "due_date": due_date, "assignee_id": assignee_id}
        return await self.call("POST", "/tickets", telegram_id, json=body)

    async def update_ticket(self, telegram_id: int, ticket_id: int, **changes) -> dict:
        return await self.call("PATCH", f"/tickets/{ticket_id}", telegram_id, json=changes)

    # Used by notifications: the bot asks as a service, not for one person

    async def summary(self) -> dict:
        """Active tickets with overdue / due_today flags."""
        return await self.call("GET", "/summary")

    async def events(self, after_id: int, limit: int = 100) -> list[dict]:
        """Ticket changes newer than after_id, oldest first."""
        return await self.call("GET", "/events", params={"after_id": after_id, "limit": limit})


api = TicketsClient()
