from datetime import date

from screen.collectors import estate, news, tickets, weather


def test_weather_parse():
    raw = {
        "current": {"time": "2026-10-27T12:15", "temperature_2m": 9.4, "apparent_temperature": 6.7,
                    "weather_code": 71, "wind_speed_10m": 4.0, "relative_humidity_2m": 91},
        "daily": {"time": ["2026-10-27"], "temperature_2m_max": [10.3], "temperature_2m_min": [-1.4],
                  "precipitation_probability_max": [80]},
    }
    w = weather.parse(raw, "Riga")
    assert w["now"]["temp"] == 9 and w["now"]["text"] == "Light snow" and w["now"]["symbol"].startswith("❄")
    assert w["today"] == {"max": 10, "min": -1, "rain": 80}


POPULAR_HTML = """
<div class="module-heading"><span>Самые популярные</span></div>
<article><figure><span class="thumbnail__number">1.</span></figure>
  <figcaption><a class="thumbnail__caption" href="/statja/a1/"><span>Первая новость</span></a>
  <div class="thumbnail__icons"><time>Вчера, 10:42</time></div></figcaption></article>
<article><figure><span class="thumbnail__number">2.</span></figure>
  <figcaption><a class="thumbnail__caption" href="/statja/a2/"><span>Вторая новость</span></a></figcaption></article>
<article><figcaption><a class="thumbnail__caption" href="/statja/a3/">Not ranked, ignored</a></figcaption></article>
"""

RSS_XML = """<?xml version="1.0"?><rss version="2.0"><channel><title>LSM</title>
<item><title>Свежая новость</title><pubDate>Tue, 27 Oct 2026 11:05:00 +0200</pubDate></item>
</channel></rss>"""


def test_news_parse_popular():
    assert news.parse_popular(POPULAR_HTML) == [
        {"rank": 1, "title": "Первая новость", "time": "Вчера, 10:42"},
        {"rank": 2, "title": "Вторая новость", "time": ""},
    ]


def test_news_parse_rss():
    assert news.parse_rss(RSS_XML) == [{"rank": 1, "title": "Свежая новость", "time": "27.10 11:05"}]


def test_due_labels():
    today = date(2026, 10, 27)
    assert tickets.due_label("2026-10-24", today) == ("3 days late", "late")
    assert tickets.due_label("2026-10-26", today) == ("1 day late", "late")
    assert tickets.due_label("2026-10-27", today) == ("today", "today")
    assert tickets.due_label("2026-10-28", today) == ("tomorrow", "soon")
    assert tickets.due_label("2026-10-31", today) == ("in 4 days", "")
    assert tickets.due_label("2026-11-15", today) == ("15 Nov", "")
    assert tickets.due_label(None, today) == ("", "")


def test_tickets_prepare_cuts_to_max_shown():
    summary = {
        "counts": {"open": 3, "in_progress": 0, "overdue": 0},
        "tickets": [{"id": i, "title": f"T{i}", "assignee_name": None, "status": "open", "due_date": None}
                    for i in range(3)],
    }
    result = tickets.prepare(summary, max_shown=2, today=date(2026, 10, 27))
    assert len(result["tickets"]) == 2 and result["hidden"] == 1
    assert result["tickets"][0]["assignee"] == "nobody"


def home(**fields):
    data = {"id": 12, "price": 26990.0, "score": 69, "town": "Sarzana", "province": "La Spezia",
            "m2": 130.0, "bedrooms": 2, "bedrooms_guessed": True, "kind": "apartment",
            "is_auction": True, "auction_date": "2026-12-16", "occupancy": "free",
            "description": "Tribunale: La Spezia rge: 12/2024 pvp: 4625138\n\nAppartamento in asta  a Sarzana. " + "Bello " * 60,
            "url": "https://www.trovacasa.it/annunci/sp-tc-69048-73960277"}
    data.update(fields)
    return data


def test_estate_card():
    card = estate.prepare(home())
    assert card["price"] == "26 990 €" and card["town"] == "Sarzana"
    assert card["specs"] == "130 m² · ~2 bedr. · apartment"
    assert card["auction"] == "Auction 16 Dec · free"
    assert card["summary"].startswith("Appartamento in asta a Sarzana.")  # court numbers gone, spaces tidied
    assert len(card["summary"]) <= estate.SUMMARY_LENGTH and card["summary"].endswith("…")
    assert card["qr"].startswith("<svg") and "viewBox" in card["qr"] and "width=" not in card["qr"]


def test_estate_card_for_a_normal_sale():
    card = estate.prepare(home(is_auction=False, m2=None, bedrooms=None, description="Casa con giardino"))
    assert card["auction"] == "" and card["specs"] == "apartment" and card["summary"] == "Casa con giardino"
