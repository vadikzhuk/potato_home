import pytest

from estate import core, db

from helpers import criteria, family, listing

CRITERIA = criteria()


@pytest.fixture
def conn():
    return db.connect(":memory:")


def add(conn, **fields) -> int:
    data = listing(**fields)
    core.save_listing(conn, data)
    return conn.execute("SELECT id FROM listings WHERE source_id = ?", (data["source_id"],)).fetchone()["id"]


def row(conn, listing_id):
    return conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()


def test_save_keeps_our_marks_and_price_history(conn):
    data = listing(price=25000.0)
    assert core.save_listing(conn, data, "2026-10-01T05:00:00+00:00") is True
    listing_id = conn.execute("SELECT id FROM listings").fetchone()["id"]
    conn.execute("UPDATE listings SET starred = 1")

    data["price"] = 22000.0
    assert core.save_listing(conn, data, "2026-10-02T05:00:00+00:00") is False
    saved = row(conn, listing_id)
    assert saved["starred"] == 1 and saved["first_price"] == 25000 and saved["price"] == 22000
    assert saved["first_seen"].startswith("2026-10-01") and saved["last_seen"].startswith("2026-10-02")
    assert [r["price"] for r in conn.execute("SELECT price FROM prices")] == [25000, 22000]


def test_why_not(conn):
    def reason(**fields):
        return core.why_not(row(conn, add(conn, **fields)), CRITERIA)

    assert reason() is None
    assert reason(price=35000.0) == "price: 35,000 €"
    assert reason(price=1000.0) == "price: 1,000 €"
    assert reason(region="Lazio") == "region: Lazio isn't searched"
    assert reason(kind="other") == "kind: other"
    assert reason(bedrooms=4) == "bedrooms: 4"
    assert reason(bedrooms=None) is None  # unknown_bedrooms: true
    assert reason(description="Vendesi nuda proprietà") == "excluded word: nuda proprietà"
    assert reason(auction_date="2020-01-01", is_auction=True).startswith("auction over")


def test_auction_on_two_sites_is_shown_once_with_both_links(conn):
    trovacasa = add(conn, title="Appartamento all'asta ad Asti", is_auction=True, price=20700.0)
    pvp = add(conn, source="pvp", is_auction=True, price=20700.0, photo=None, m2=None,
              auction_date="2099-12-01", occupancy="free", url="https://pvp.example/1")
    # Another auction: this site shows the base price, PVP the lowest offer (75% of it)
    other = add(conn, title="Casa all'asta ad Asti", is_auction=True, price=20000.0)
    other_pvp = add(conn, source="pvp", is_auction=True, price=15000.0 + 1, photo=None, m2=None)
    assert core.link_duplicates(conn, CRITERIA) == 2
    assert row(conn, other_pvp)["duplicate_of"] == other
    assert row(conn, pvp)["duplicate_of"] == trovacasa  # the one with a photo stays

    shown = core.get_listing(conn, CRITERIA, trovacasa)
    assert shown["auction_date"] == "2099-12-01" and shown["occupancy"] == "free"  # taken from PVP
    assert [link["source"] for link in shown["links"]] == ["trovacasa", "pvp"]


def test_same_property_twice_on_one_site(conn):
    first = add(conn, price=20000.0, m2=80.0)
    add(conn, price=20200.0, m2=82.0)          # the same flat from another agency
    add(conn, price=20000.0, m2=120.0)         # another flat in the same town
    add(conn, price=20000.0, m2=80.0, town="Alba")
    assert core.link_duplicates(conn, CRITERIA) == 1
    assert len(core.top(conn, CRITERIA)) == 3
    assert core.get_listing(conn, CRITERIA, first)["links"][1]["url"]


def test_score_prefers_cheap_per_m2_good_condition_and_extras(conn):
    for _ in range(5):  # the province median: 250 €/m²
        add(conn, price=20000.0, m2=80.0, town=None)
    cheap = add(conn, price=15000.0, m2=120.0, description="abitabile, giardino e terrazzo", town=None)
    ruin = add(conn, price=15000.0, m2=120.0, description="rudere da ristrutturare", town=None)
    scores = {l["id"]: l["score"] for l in core.top(conn, CRITERIA, limit=100)}
    assert scores[cheap] > scores[ruin] > min(scores.values()) - 1
    assert scores[cheap] == max(scores.values())

    details = core.get_listing(conn, CRITERIA, cheap)["score_details"]
    assert details["good"] == ["abitabile"] and details["extras"] == ["giardino", "terrazz"]
    assert sum(details["points"].values()) == scores[cheap]


def test_preferred_province_bonus(conn):
    listing_id = add(conn)
    before = core.get_listing(conn, CRITERIA, listing_id)["score"]
    preferred = criteria(scoring={**CRITERIA["scoring"], "preferred_provinces": ["Asti"]})
    assert core.get_listing(conn, preferred, listing_id)["score"] == min(100, before + 10)


def test_digest_new_listings_and_price_drops(conn):
    old = add(conn, price=25000.0)
    conn.execute("UPDATE listings SET first_seen = '2026-01-01T00:00:00+00:00', starred = 1")
    first_run = core.start_run(conn)
    core.finish_run(conn, first_run, 1, 1, [])
    conn.execute("UPDATE runs SET started_at = '2026-01-01T00:00:00+00:00', finished_at = '2026-01-01T00:10:00+00:00'")
    conn.execute("UPDATE prices SET seen_at = '2026-01-01T00:00:00+00:00'")

    second_run = core.start_run(conn)
    new = add(conn)
    auction = add(conn, is_auction=True, auction_date="2099-01-01", title="Casa all'asta ad Asti", m2=50.0)
    core.save_listing(conn, {**listing(price=21000.0), "source_id": row(conn, old)["source_id"]})
    core.finish_run(conn, second_run, 3, 2, [])

    result = core.digest(conn, CRITERIA, after_run=first_run)
    assert [l["id"] for l in result["new"]] == [new]
    assert [l["id"] for l in result["auctions"]] == [auction]
    assert [(l["id"], l["old_price"], l["price"]) for l in result["price_drops"]] == [(old, 25000, 21000)]

    high_bar = criteria(digest={"min_score": 101})
    assert core.digest(conn, high_bar)["new"] == []


def test_flags_need_write_access(conn):
    listing_id = add(conn)
    people = family()
    with pytest.raises(core.Forbidden):
        core.set_flags(conn, CRITERIA, people.get(3), listing_id, hidden=True)  # Kid: read only
    assert core.set_flags(conn, CRITERIA, people.get(2), listing_id, hidden=True)["hidden"]
    assert core.top(conn, CRITERIA) == []
    assert core.get_listing(conn, CRITERIA, listing_id)["why_not"] == "hidden"
    with pytest.raises(core.Invalid):
        core.set_flags(conn, CRITERIA, people.get(2), listing_id, price=1)
