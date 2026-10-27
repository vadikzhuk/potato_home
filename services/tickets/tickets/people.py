"""Who is who: people and their access to tickets come from the users service.

Tickets only store user ids. To check permissions and to show names, we ask the
users service for everyone and keep the answer for a few seconds, so a page with
many tickets doesn't mean many requests.
"""

import os
import time
from dataclasses import dataclass
from typing import Callable

import httpx

SERVICE = "tickets"  # our name in the users service's access table
LEVELS = ("read", "write", "admin")


class Unavailable(Exception):
    """The users service can't be reached."""


@dataclass
class Person:
    id: int
    name: str
    telegram_id: int | None
    is_active: bool
    level: str | None  # access to tickets: read, write, admin, or None

    def can(self, needed: str) -> bool:
        """Active and with at least the `needed` level? Levels include the lower ones."""
        return self.is_active and self.level is not None and LEVELS.index(self.level) >= LEVELS.index(needed)


class People:
    def __init__(self, load: Callable[[], list[dict]], max_age: float = 5):
        self._load = load  # returns users as the users service sends them
        self._max_age = max_age
        self._by_id: dict[int, Person] = {}
        self._loaded_at = 0.0

    @classmethod
    def from_service(cls) -> "People":
        """Read people from the users service at USERS_URL."""
        def load() -> list[dict]:
            try:
                response = httpx.get(
                    (os.environ.get("USERS_URL") or "http://localhost:8002") + "/users",
                    params={"include_inactive": True},
                    headers={"X-Api-Token": os.environ.get("API_TOKEN", "")},
                    timeout=5,
                )
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise Unavailable(f"Users service is not reachable ({type(error).__name__}).") from None
            return response.json()
        return cls(load)

    def _people(self, refresh: bool = False) -> dict[int, Person]:
        if refresh or time.monotonic() - self._loaded_at > self._max_age:
            self._by_id = {
                u["id"]: Person(u["id"], u["name"], u["telegram_id"], u["is_active"], u["access"].get(SERVICE))
                for u in self._load()
            }
            self._loaded_at = time.monotonic()
        return self._by_id

    def _find(self, match: Callable[[Person], bool]) -> Person | None:
        """First person matching; if nobody does, ask again in case they were just added."""
        for refresh in (False, True):
            for person in self._people(refresh).values():
                if match(person):
                    return person
        return None

    def all(self) -> list[Person]:
        return sorted(self._people().values(), key=lambda p: p.id)

    def get(self, user_id: int | None) -> Person | None:
        return None if user_id is None else self._find(lambda p: p.id == user_id)

    def by_telegram(self, telegram_id: int) -> Person | None:
        return self._find(lambda p: p.telegram_id == telegram_id)

    def by_name(self, name: str) -> Person | None:
        return self._find(lambda p: p.name.lower() == name.strip().lower())

    def name(self, user_id: int | None) -> str | None:
        person = self.get(user_id)
        return person.name if person else None
