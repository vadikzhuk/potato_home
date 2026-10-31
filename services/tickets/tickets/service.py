"""The terminal's way to change things: through the running tickets service.

Only the service writes its database. On a Mac, two programs writing one SQLite
file in Docker's shared folder can corrupt it, so the `tickets` command opens the
database read-only and sends every change to the service's API.
"""

import os

import httpx

from . import core
from .people import Person

ERRORS = {403: core.Forbidden, 404: core.NotFound}


def url() -> str:
    """TICKETS_URL, or the service in the same container (where `tickets` runs)."""
    return os.environ.get("TICKETS_URL") or "http://localhost:8000"


def http() -> httpx.Client:
    """Tests replace this with a client that talks to the API directly."""
    return httpx.Client(base_url=url(), headers={"X-Api-Token": os.environ.get("API_TOKEN", "")}, timeout=30)


def call(method: str, path: str, actor: Person | None, **kwargs):
    """Ask the service on behalf of `actor`; its "no" becomes a TicketsError with its message."""
    headers = {"X-User-Id": str(actor.id)} if actor else {}
    try:
        with http() as client:
            response = client.request(method, path, headers=headers, **kwargs)
    except httpx.HTTPError:
        raise core.TicketsError(f"The tickets service doesn't answer at {url()}. "
                                "Is it running? docker compose up -d tickets") from None
    if response.is_error:
        try:
            message = response.json()["detail"]
        except (ValueError, KeyError):
            message = response.text
        raise ERRORS.get(response.status_code, core.TicketsError)(str(message))
    return response.json()
