"""Trovacasa.it: agencies' and private listings, court auctions among them.

There is no API, so we read the search result pages: one province at a time,
24 listings a page, newest first, only up to the maximum price. robots.txt
allows these pages; we pause between them so it's like one person browsing.

If the site changes its HTML and nothing is found, parse_page() is the place to fix.
"""

import re
from collections.abc import Callable, Iterator

import httpx
from bs4 import BeautifulSoup

from .. import parse
from .web import request

NAME = "trovacasa"
BASE = "https://www.trovacasa.it"
NEWEST_FIRST = 7  # the site's "Ordinamento" value for "Data pubblicazione"
MAX_PAGES = 100   # per province, a safety stop

# Region -> {the province's name in Trovacasa addresses: its name for us}
PROVINCES = {
    "Piemonte": {"alessandria": "Alessandria", "asti": "Asti", "biella": "Biella", "cuneo": "Cuneo",
                 "novara": "Novara", "torino": "Torino", "verbano-cusio-ossola": "Verbano-Cusio-Ossola",
                 "vercelli": "Vercelli"},
    "Liguria": {"genova": "Genova", "imperia": "Imperia", "la-spezia": "La Spezia", "savona": "Savona"},
    "Toscana": {"arezzo": "Arezzo", "firenze": "Firenze", "grosseto": "Grosseto", "livorno": "Livorno",
                "lucca": "Lucca", "massa-carrara": "Massa-Carrara", "pisa": "Pisa", "pistoia": "Pistoia",
                "prato": "Prato", "siena": "Siena"},
    "Lazio": {"frosinone": "Frosinone", "latina": "Latina", "rieti": "Rieti", "roma": "Roma",
              "viterbo": "Viterbo"},
}


def fetch(search: dict, http: httpx.Client, pause: Callable[[], None]) -> Iterator[dict]:
    for region in search["regions"]:
        for slug, province in PROVINCES[region].items():
            for page in range(1, MAX_PAGES + 1):
                params = {"PrezzoMin": search["min_price"], "PrezzoMax": search["max_price"],
                          "Ordinamento": NEWEST_FIRST}
                if page > 1:
                    params["page"] = page
                html = request(http, "GET", f"{BASE}/case-in-vendita/provincia-di-{slug}", params=params).text
                yield from parse_page(html, region, province)
                pause()
                if not has_page(html, page + 1):
                    break


def has_page(html: str, page: int) -> bool:
    """Does the page link to result page number `page`?"""
    return re.search(rf"[?&;]page={page}\b", html) is not None


def parse_page(html: str, region: str, province: str) -> list[dict]:
    """Every listing card on a search result page."""
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    for card in soup.select(".js_card_immobile"):
        link = card.select_one("a.card__title")
        if link is None:
            continue
        title = link.get_text(" ", strip=True).replace("’", "'")
        street = _text(card, ".card__quartiere")
        info = " ".join(span.get_text(" ", strip=True) for span in card.select(".card__info"))  # "95 m² 4 locali"
        description = _text(card, ".card__description")
        features = [tag.get_text(" ", strip=True) for tag in card.select(".annuncioTag")]
        photo = card.select_one("img[data-src]")
        rooms = parse.rooms_in(info)
        bedrooms, guessed = parse.bedrooms_from(rooms, description)
        listings.append({
            "source": NAME,
            "source_id": link["href"].rsplit("-", 1)[-1],  # /annunci/at-tc-87054-73956135
            "url": BASE + link["href"],
            "title": title,
            "kind": parse.kind_of(title),
            "is_auction": "all'asta" in title.lower() or any("asta giudiziaria" in f.lower() for f in features),
            "region": region,
            "province": province,
            "town": parse.town_in_title(title),
            "address": street or None,
            "price": parse.price_in(_text(card, ".card__price")),
            "m2": parse.m2_in(info),
            "rooms": rooms,
            "bedrooms": bedrooms,
            "bedrooms_guessed": guessed,
            "description": description,
            "features": features,
            "photo": photo["data-src"] if photo else None,
            "auction_date": None,
            "occupancy": None,
        })
    return listings


def _text(card, selector: str) -> str:
    element = card.select_one(selector)
    return element.get_text(" ", strip=True) if element else ""
