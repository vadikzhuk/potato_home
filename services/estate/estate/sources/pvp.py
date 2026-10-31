"""PVP, the Portale delle Vendite Pubbliche (pvp.giustizia.it): Italy's official
list of court auctions. Every judicial property sale must be published here,
so it covers the auction sites (Astegiudiziarie and others) as well.

Its web page gets the lots from a JSON API, which we ask the same way.
Rooms and m² are only in the lot's description, so they're read from the text.

The price we keep is the lowest offer the court accepts: by law 75% of the
base price (the base price is listed in the features). Trovacasa shows auctions
the same way, so prices compare like for like.

The "ric-496b258c-986a1b71" part of the address may change when PVP updates its
site. If this source starts failing with 404: open pvp.giustizia.it, search
for anything, and copy the new address of the ".../ricerca/vendite" request
from the browser's developer tools (Network tab).
"""

from collections.abc import Callable, Iterator

import httpx

from .. import parse
from .web import request

NAME = "pvp"
SEARCH_URL = "https://pvp.giustizia.it/ric-496b258c-986a1b71/ric-ms/ricerca/vendite"
DETAIL_URL = "https://pvp.giustizia.it/pvp/it/detail_annuncio.page?idAnnuncio={}"
PAGE_SIZE = 50
UPCOMING = 1  # the API's "filtroAnnunci" for auctions that haven't happened yet

OCCUPANCY = {"LIBER": "free", "OCCUP": "occupied", "OCCST": "occupied", "INCOR": "being freed"}
HOUSE_CATEGORIES = {"VILLA", "ABITAZIONE_IN_VILLE", "ABITAZIONE_IN_VILLINI", "ABITAZIONE_TIPO_RUR",
                    "FABBRICATO", "PORZIONE_DI_IMMOBILE"}
TITLE_WORDS = {"apartment": "Appartamento", "house": "Casa", "other": "Immobile"}
MIN_OFFER = 0.75  # the lowest offer accepted, as a share of the base price


def fetch(search: dict, http: httpx.Client, pause: Callable[[], None]) -> Iterator[dict]:
    if not search["auctions"]:
        return
    for region in search["regions"]:
        body = {"flagRicerca": 1, "nazione": "Italia", "regione": region, "filtroAnnunci": UPCOMING,
                "tipoLotto": "IMMOBILI", "categoriaLotto": "IMMOBILE_RESIDENZIALE",
                # The API filters by base price; we want lots whose lowest offer is in range
                "prezzoBaseAstaMin": round(search["min_price"] / MIN_OFFER),
                "prezzoBaseAstaMax": round(search["max_price"] / MIN_OFFER)}
        page = 0
        while True:
            params = {"language": "it", "page": page, "size": PAGE_SIZE, "sort": "dataOraVendita,asc"}
            result = request(http, "POST", SEARCH_URL, params=params, json=body).json()["body"]
            for lot in result["content"]:
                yield to_listing(lot, region)
            pause()
            page += 1
            if page >= result["totalPages"]:
                break


def kind_of(lot: dict) -> str:
    categories = set(lot["categoriaBene"] or [])
    if categories & HOUSE_CATEGORIES:
        return "house"
    if "APPARTAMENTO" in categories:
        return "apartment"
    if any(c.startswith("ABITAZIONE") for c in categories):  # a home, but which kind isn't said
        kind = parse.kind_of(lot["descLotto"] or "")
        return kind if kind != "other" else "apartment"
    return "other"


def to_listing(lot: dict, region: str) -> dict:
    address = lot["indirizzo"]
    text = lot["descLotto"] or ""
    kind = kind_of(lot)
    rooms = parse.rooms_in(text)
    bedrooms, guessed = parse.bedrooms_from(rooms, text)
    base = lot["prezzoBaseAsta"] or None
    features = [f"prezzo base {base:,.0f} €".replace(",", ".")] if base else []
    photo = lot.get("immagineCover") or lot.get("immagine")
    return {
        "source": NAME,
        "source_id": str(lot["id"]),
        "url": DETAIL_URL.format(lot["id"]),
        "title": f"{TITLE_WORDS[kind]} all'asta a {address['citta']}",
        "kind": kind,
        "is_auction": True,
        "region": region,
        "province": address["provincia"],
        "town": address["citta"],
        "address": address["via"] or None,
        "price": lot.get("offertaMinima") or (base and round(base * MIN_OFFER, 2)),
        "m2": parse.m2_in(text),
        "rooms": rooms,
        "bedrooms": bedrooms,
        "bedrooms_guessed": guessed,
        "description": text,
        "features": features,
        "photo": photo if photo and photo.startswith("http") else None,
        "auction_date": lot["dataVendita"],
        "occupancy": OCCUPANCY.get((lot["disponibilita"] or [None])[0]),
    }
