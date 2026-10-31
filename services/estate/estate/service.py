"""The terminal's way to change things: through the running estate service.

Only the service writes its database. On a Mac, two programs writing one SQLite
file in Docker's shared folder can corrupt it, so the `estate` command opens the
database read-only and sends every change to the service's API.
"""

import os

import httpx

from . import core

ERRORS = {403: core.Forbidden, 404: core.NotFound, 409: core.EstateError}


def url() -> str:
    """ESTATE_URL, or the service in the same container (where `estate` runs)."""
    return os.environ.get("ESTATE_URL") or "http://localhost:8000"


def http() -> httpx.Client:
    """Tests replace this with a client that talks to the API directly."""
    return httpx.Client(base_url=url(), headers={"X-Api-Token": os.environ.get("API_TOKEN", "")}, timeout=30)


def call(method: str, path: str, **kwargs):
    """Ask the service (with the API token alone: the terminal is trusted).
    Its "no" becomes an EstateError with its message."""
    headers = {}
    try:
        with http() as client:
            response = client.request(method, path, headers=headers, **kwargs)
    except httpx.HTTPError:
        raise core.EstateError(f"The estate service doesn't answer at {url()}. "
                               "Is it running? docker compose up -d estate") from None
    if response.is_error:
        try:
            message = response.json()["detail"]
        except (ValueError, KeyError):
            message = response.text
        raise ERRORS.get(response.status_code, core.EstateError)(str(message))
    return response.json()
