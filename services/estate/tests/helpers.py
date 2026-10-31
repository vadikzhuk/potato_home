"""Things the tests share: criteria, listings and people, without the network."""

import copy

from estate.people import People

CRITERIA = {
    "search": {"regions": ["Piemonte", "Liguria"], "max_price": 30000, "min_price": 3000,
               "bedrooms": {"min": 2, "max": 3}, "unknown_bedrooms": True,
               "kinds": ["apartment", "house"], "auctions": True},
    "exclude_words": ["nuda proprietà", "quota indivisa"],
    "scoring": {
        "weights": {"price_per_m2": 35, "price": 15, "condition": 20, "extras": 10, "price_drop": 10, "details": 10},
        "good_condition": ["abitabile", "ristrutturat"],
        "bad_condition": ["da ristrutturare", "rudere"],
        "extras": ["giardino", "terrazz"],
        "preferred_provinces": [],
        "preferred_bonus": 10,
    },
    "digest": {"top": 10, "auctions": 5, "min_score": 0},
    "fetch": {"time": "05:00", "pause_seconds": 0, "gone_after_days": 3},
}


def criteria(**changes) -> dict:
    """A copy of CRITERIA; changes like search={"max_price": 20000} are merged in."""
    result = copy.deepcopy(CRITERIA)
    for section, values in changes.items():
        if isinstance(values, dict):
            result[section].update(values)
        else:
            result[section] = values
    return result


_ids = iter(range(1, 10**6))


def listing(**fields) -> dict:
    """A listing as a source yields it: a 2-bedroom apartment in Asti for 20 000 €."""
    data = {
        "source": "trovacasa", "source_id": str(next(_ids)), "url": "https://example.com/1",
        "title": "Appartamento ad Asti via Roma", "kind": "apartment", "is_auction": False,
        "region": "Piemonte", "province": "Asti", "town": "Asti", "address": "Via Roma",
        "price": 20000.0, "m2": 80.0, "rooms": 3, "bedrooms": 2, "bedrooms_guessed": True,
        "description": "Appartamento abitabile", "features": [], "photo": "https://example.com/p.jpg",
        "auction_date": None, "occupancy": None,
    }
    data.update(fields)
    return data


def user(id, name, estate=None, telegram_id=None, active=True):
    access = {"estate": estate} if estate else {}
    return {"id": id, "name": name, "telegram_id": telegram_id, "is_active": active,
            "created_at": "2026-10-27T10:00:00+00:00", "access": access}


def family() -> People:
    """Alex (estate admin), Anna (write), Kid (read), Bob (no access)."""
    users = [user(1, "Alex", "admin", 111), user(2, "Anna", "write", 222),
             user(3, "Kid", "read", 333), user(4, "Bob", telegram_id=444)]
    return People(load=lambda: users)
