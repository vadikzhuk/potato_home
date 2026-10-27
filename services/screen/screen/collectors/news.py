"""Trending news from rus.lsm.lv.

The "Самые популярные" page has no API, so we read its HTML. If LSM changes the
page and nothing can be found there, we fall back to the RSS feed (latest news,
not trending), so the panel keeps working until this file is fixed.
"""

from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (potato_home info screen)"}


def fetch(config: dict) -> dict:
    news = config["news"]
    count = news["count"]
    try:
        items = parse_popular(_get(news["popular_url"]))[:count]
    except httpx.HTTPError:
        items = []
    if items:
        return {"source": "popular", "items": items}
    return {"source": "latest", "items": parse_rss(_get(news["rss_url"]))[:count]}


def parse_popular(html: str) -> list[dict]:
    """Numbered articles on the popular page: rank, title and publish time."""
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for article in soup.select("article"):
        number = article.select_one(".thumbnail__number")
        caption = article.select_one("a.thumbnail__caption")
        if not number or not caption or caption["href"] in seen:
            continue
        seen.add(caption["href"])
        published = article.select_one("time")
        items.append({
            "rank": len(items) + 1,
            "title": caption.get_text(" ", strip=True),
            "time": published.get_text(strip=True) if published else "",
        })
    return items


def parse_rss(xml: str) -> list[dict]:
    items = []
    for item in ElementTree.fromstring(xml).iter("item"):
        pub_date = item.findtext("pubDate")
        items.append({
            "rank": len(items) + 1,
            "title": (item.findtext("title") or "").strip(),
            "time": parsedate_to_datetime(pub_date).strftime("%d.%m %H:%M") if pub_date else "",
        })
    return items


def _get(url: str) -> str:
    response = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
    response.raise_for_status()
    return response.text
