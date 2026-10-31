"""Asking websites, the same polite way for every source."""

import time

import httpx

# Says honestly who is asking. Both sites answer it; if one ever stops, look here first.
HEADERS = {"User-Agent": "potato_home/0.1 (personal home server; daily check of a few search pages)",
           "Accept-Language": "it-IT,it;q=0.9"}
RETRIES = 3
RETRY_WAIT = 30  # seconds: a busy site often answers again a bit later


def client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)


def request(http: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """The response, after up to RETRIES tries; the last error is raised."""
    for attempt in range(1, RETRIES + 1):
        try:
            response = http.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            if attempt == RETRIES:
                raise
            time.sleep(RETRY_WAIT)
