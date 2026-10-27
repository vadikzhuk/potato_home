"""Talks to the users service: who is who, and their access to each service."""

import os

from ..common import ApiError, ServiceClient


class UsersClient(ServiceClient):
    def __init__(self, **kwargs):
        super().__init__(os.environ.get("USERS_URL", "http://users:8000"), "users", **kwargs)

    async def whoami(self, telegram_id: int) -> dict | None:
        """The user with this Telegram id, or None if there is none."""
        try:
            return await self.call("GET", f"/users/by-telegram/{telegram_id}")
        except ApiError as error:
            if error.status == 404:
                return None
            raise

    async def users(self, telegram_id: int | None = None, include_inactive: bool = False) -> list[dict]:
        """All users. With `telegram_id`, asks on behalf of that person (needs users read)."""
        return await self.call("GET", "/users", telegram_id, params={"include_inactive": include_inactive})

    async def user_by_name(self, name: str) -> dict:
        return await self.call("GET", f"/users/by-name/{name.strip()}")

    async def add_user(self, telegram_id: int, name: str, new_telegram_id: int | None = None) -> dict:
        return await self.call("POST", "/users", telegram_id, json={"name": name, "telegram_id": new_telegram_id})

    async def update_user(self, telegram_id: int, user_id: int, **changes) -> dict:
        return await self.call("PATCH", f"/users/{user_id}", telegram_id, json=changes)

    async def grant(self, telegram_id: int, user_id: int, service: str, level: str) -> dict:
        return await self.call("PUT", f"/users/{user_id}/access/{service}", telegram_id, json={"level": level})

    async def revoke(self, telegram_id: int, user_id: int, service: str) -> dict:
        return await self.call("DELETE", f"/users/{user_id}/access/{service}", telegram_id)


api = UsersClient()
