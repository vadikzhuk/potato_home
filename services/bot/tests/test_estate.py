from bot.estate import digest, texts


def listing(id=12, **fields):
    data = {"id": id, "title": "Casa Indipendente a Montoggio località Montemoro", "url": "https://t.example/12",
            "price": 9000.0, "m2": 75.0, "bedrooms": 2, "bedrooms_guessed": True, "kind": "house",
            "town": "Montoggio", "province": "Genova", "region": "Liguria", "is_auction": False,
            "auction_date": None, "occupancy": None, "starred": False, "hidden": False, "score": 75,
            "score_details": {"good": [], "bad": ["da riordinare"], "extras": ["giardino"], "points": {}},
            "description": "Casa semindipendente " * 100, "photo": None,
            "links": [{"source": "trovacasa", "url": "https://t.example/12"}]}
    data.update(fields)
    return data


def test_listing_line():
    line = texts.listing_line(listing(is_auction=True, starred=True))
    assert line.startswith("🔨 ⭐ <b>#12</b> 9 000 € · 75 m² · ~2 bedr. · Montoggio (Genova) · score 75")
    assert '<a href="https://t.example/12">Casa Indipendente' in line


def test_card_fits_under_a_photo():
    card = texts.listing_card(listing(is_auction=True, auction_date="2026-12-03", occupancy="free",
                                      prices=[{"price": 12000}, {"price": 9000}]))
    assert len(card) <= texts.CAPTION_LIMIT and card.endswith("…")
    assert "🔨 Auction on 2026-12-03 · 🟢 free" in card
    assert "📉 12 000 € → 9 000 €" in card
    assert "Score <b>75</b>: giardino, ✗ da riordinare" in card


def test_buttons_follow_the_flags():
    buttons = texts.listing_buttons(listing(starred=True))
    star, hide = buttons.inline_keyboard[0]
    assert (star.text, star.callback_data) == ("★ Unstar", "estate:star:12:0")
    assert hide.callback_data == "estate:hide:12:1"
    assert buttons.inline_keyboard[1][0].url == "https://t.example/12"


def test_digest_message():
    run = {"id": 3, "added": 41}
    empty = {"run": run, "new": [], "auctions": [], "price_drops": []}
    assert texts.digest_message(empty) is None
    message = texts.digest_message({**empty, "new": [listing()], "price_drops": [listing(7, old_price=12000.0)]})
    assert "41 new on the sites today" in message
    assert "#12" in message and "📉 was 12 000 €" in message and "New auctions" not in message


def test_digest_goes_to_people_with_estate_access():
    def user(name, telegram_id, access):
        return {"name": name, "telegram_id": telegram_id, "is_active": True, "access": access}
    users = [user("Alex", 111, {"estate": "admin"}), user("Kid", 333, {"estate": "read"}),
             user("Bob", 444, {"tickets": "write"}), user("Nobody", None, {"estate": "read"})]
    assert [u["name"] for u in digest.recipients(users)] == ["Alex", "Kid"]


def test_a_long_digest_is_cut_to_fit_telegram():
    many = [listing(i, title="Casa " + "molto bella " * 20) for i in range(30)]
    message = texts.digest_message({"run": {"id": 1, "added": 30}, "new": many, "auctions": many[:5], "price_drops": []})
    assert len(message) <= texts.MESSAGE_LIMIT
    assert "#0" in message and "New auctions" in message
