"""What the bot says about listings: message texts and buttons. No Telegram or HTTP calls here.

Button presses come back as "callback data" strings starting with "estate:":
  estate:show:12          show listing 12
  estate:star:12:1        star listing 12 (0 = unstar)
  estate:hide:12:1        hide listing 12 (0 = show it again)
  estate:list:top         the best listings (or estate:list:auctions, estate:list:starred)
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from ..common import esc

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)  # lists have many links: no big preview card
CAPTION_LIMIT = 1024  # Telegram's limit for text under a photo
MESSAGE_LIMIT = 4096  # and for a message
SOURCE_NAMES = {"trovacasa": "Trovacasa", "pvp": "PVP (court auction)"}
OCCUPANCY = {"free": "🟢 free", "occupied": "🔴 occupied", "being freed": "🟡 being freed"}
LIST_TITLES = {"top": "Best listings now", "auctions": "Best auctions now", "starred": "⭐ Starred"}

HELP = """<b>Estate</b> (cheap homes in Italy)
/estate - menu
/estate 12 - show listing #12, with buttons to ⭐ star or hide it
/estate_top - the best listings now
/estate_auctions - the best court auctions now
/estate_starred - listings you're watching
Every morning, after the sites are checked, new finds come by themselves."""


def euros(value: float | None) -> str:
    return f"{value:,.0f} €".replace(",", " ") if value is not None else "?"


def bedrooms(listing: dict) -> str:
    if listing["bedrooms"] is None:
        return "? bedrooms"
    return f"{'~' if listing['bedrooms_guessed'] else ''}{listing['bedrooms']} bedr."


def listing_line(listing: dict) -> str:
    """🔨 #12 9 000 € · 75 m² · ~2 bedr. · Montoggio (Genova) · 75
    and the title as a link on the second line."""
    parts = [f"<b>#{listing['id']}</b> {euros(listing['price'])}"]
    if listing["m2"]:
        parts.append(f"{listing['m2']:.0f} m²")
    parts.append(bedrooms(listing))
    parts.append(f"{esc(listing['town'] or '?')} ({esc(listing['province'] or '?')})")
    if listing["score"] is not None:
        parts.append(f"score {listing['score']}")
    icons = ("🔨 " if listing["is_auction"] else "") + ("⭐ " if listing["starred"] else "")
    return f"{icons}{' · '.join(parts)}\n<a href=\"{esc(listing['url'])}\">{esc(listing['title'][:70])}</a>"


def listing_list(title: str, listings: list[dict]) -> str:
    if not listings:
        return f"<b>{esc(title)}</b>\n\nNothing here."
    return f"<b>{esc(title)}</b>\n\n" + "\n\n".join(listing_line(l) for l in listings)


def list_buttons(listings: list[dict]) -> InlineKeyboardMarkup | None:
    """One button per listing (up to 15) that opens it, two in a row."""
    buttons = [InlineKeyboardButton(f"#{l['id']} {euros(l['price'])} {(l['town'] or '')[:14]}",
                                    callback_data=f"estate:show:{l['id']}") for l in listings[:15]]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows) if rows else None


def menu_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(LIST_TITLES[kind], callback_data=f"estate:list:{kind}")
                                  for kind in ("top", "auctions")],
                                 [InlineKeyboardButton(LIST_TITLES["starred"], callback_data="estate:list:starred")]])


def listing_card(listing: dict, limit: int = CAPTION_LIMIT) -> str:
    """Everything about one listing, short enough to go under its photo."""
    lines = [f"<b>#{listing['id']} {esc(listing['title'])}</b>" + (" ⭐" if listing["starred"] else "")]
    size = f"{listing['m2']:.0f} m² · " if listing["m2"] else ""
    lines.append(f"<b>{euros(listing['price'])}</b> · {size}{bedrooms(listing)} · {listing['kind']}")
    lines.append(f"📍 {esc(listing['town'] or '?')}, {esc(listing['province'] or '?')}, {esc(listing['region'])}")
    if listing["is_auction"]:
        when = f" on {listing['auction_date']}" if listing["auction_date"] else ""
        occupancy = f" · {OCCUPANCY[listing['occupancy']]}" if listing["occupancy"] in OCCUPANCY else ""
        lines.append(f"🔨 Auction{when}{occupancy}. The price is the lowest offer accepted.")
    prices = listing.get("prices") or []
    if len(prices) > 1:
        lines.append("📉 " + " → ".join(euros(p["price"]) for p in prices))
    details = listing["score_details"]
    if details:
        reasons = [*details["good"], *details["extras"], *(f"✗ {word}" for word in details["bad"])]
        lines.append(f"Score <b>{listing['score']}</b>" + (f": {esc(', '.join(reasons))}" if reasons else ""))
    if listing.get("why_not"):
        lines.append(f"<i>Not in lists: {esc(listing['why_not'])}</i>")

    head = "\n".join(lines)
    room = limit - len(head) - 10
    description = listing["description"]
    if room > 50 and description:
        if len(description) > room:
            description = description[: room - 1].rsplit(" ", 1)[0] + "…"
        head += "\n\n" + esc(description)
    return head


def listing_buttons(listing: dict) -> InlineKeyboardMarkup:
    """Star / hide, and a link to every site that lists it."""
    listing_id = listing["id"]
    star = ("★ Unstar", 0) if listing["starred"] else ("⭐ Star", 1)
    hide = ("👁 Show again", 0) if listing["hidden"] else ("🙈 Hide", 1)
    rows = [[InlineKeyboardButton(star[0], callback_data=f"estate:star:{listing_id}:{star[1]}"),
             InlineKeyboardButton(hide[0], callback_data=f"estate:hide:{listing_id}:{hide[1]}")]]
    rows += [[InlineKeyboardButton(f"Open on {SOURCE_NAMES.get(link['source'], link['source'])}", url=link["url"])]
             for link in listing["links"]]
    return InlineKeyboardMarkup(rows)


def digest_message(digest: dict) -> str | None:
    """The daily message, or None when there's nothing worth sending.
    If it's too long for Telegram, the lowest-scored listings are left out."""
    if not (digest["new"] or digest["auctions"] or digest["price_drops"]):
        return None
    text = _digest_text(digest)
    while len(text) > MESSAGE_LIMIT:
        longest = max(("new", "auctions", "price_drops"), key=lambda part: len(digest[part]))
        digest = {**digest, longest: digest[longest][:-1]}
        text = _digest_text(digest)
    return text


def _digest_text(digest: dict) -> str:
    run = digest["run"]
    parts = [f"🏡 <b>Homes in Italy</b>: {run['added']} new on the sites today. The best of them:"]
    if digest["new"]:
        parts.append("\n\n".join(listing_line(l) for l in digest["new"]))
    if digest["auctions"]:
        parts.append("🔨 <b>New auctions</b>\n\n" + "\n\n".join(listing_line(l) for l in digest["auctions"]))
    if digest["price_drops"]:
        drops = [f"{listing_line(l)}\n📉 was {euros(l['old_price'])}" for l in digest["price_drops"]]
        parts.append("📉 <b>Starred, now cheaper</b>\n\n" + "\n\n".join(drops))
    return "\n\n".join(parts)


def digest_buttons(digest: dict) -> InlineKeyboardMarkup | None:
    return list_buttons(digest["new"] + digest["auctions"] + digest["price_drops"])
