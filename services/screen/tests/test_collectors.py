from datetime import date

from screen.collectors import news, tickets, weather


def test_weather_parse():
    hours = [f"2026-10-27T{h:02d}:00" for h in range(24)] + [f"2026-10-28T{h:02d}:00" for h in range(24)]
    raw = {
        "current": {"time": "2026-10-27T12:15", "temperature_2m": 9.4, "apparent_temperature": 6.7,
                    "weather_code": 3, "wind_speed_10m": 4.0, "relative_humidity_2m": 91},
        "hourly": {"time": hours, "temperature_2m": [5.0] * 48, "weather_code": [61] * 48,
                   "precipitation_probability": [70] * 48},
        "daily": {"time": ["2026-10-27", "2026-10-28"], "weather_code": [0, 71],
                  "temperature_2m_max": [10.3, 2.0], "temperature_2m_min": [6.9, -1.4],
                  "precipitation_probability_max": [0, 80]},
    }
    w = weather.parse(raw, "Riga")
    assert w["now"]["temp"] == 9 and w["now"]["text"] == "Overcast"
    assert [h["time"] for h in w["hours"]] == ["15:00", "18:00", "21:00", "00:00",
                                               "03:00", "06:00", "09:00", "12:00"]
    assert [d["name"] for d in w["days"]] == ["Today", "Wed"]
    assert w["days"][1]["symbol"].startswith("❄")


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
