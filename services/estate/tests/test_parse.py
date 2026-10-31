import pytest

from estate import parse


@pytest.mark.parametrize("text, kind", [
    ("Appartamento all'asta ad Asti", "apartment"),
    ("Casa Indipendente a Bra", "house"),
    ("Villetta a schiera a Alba", "house"),
    ("Trilocale a Genova", "apartment"),
    ("Appartamento con box a Biella", "apartment"),  # the first word decides
    ("Box auto a Torino", "other"),
    ("Something else", "other"),
])
def test_kind_of(text, kind):
    assert parse.kind_of(text) == kind


@pytest.mark.parametrize("text, bedrooms", [
    ("soggiorno, tre camere, bagno", 3),
    ("soggiorno-cucina, trecamere, bagno", 3),       # a real typo from a listing
    ("2 camere da letto e cucina", 2),
    ("cucina, camera da letto, bagno", 1),
    ("cucina, camera, cameretta, camera, bagno", 2),  # counted one by one
    ("ampio soggiorno e bagno", None),
])
def test_bedrooms_in(text, bedrooms):
    assert parse.bedrooms_in(text) == bedrooms


def test_rooms_and_bedrooms_from_rooms():
    assert parse.rooms_in("95 m² 4 locali") == 4
    assert parse.rooms_in("Bel trilocale") == 3
    assert parse.bedrooms_from(4, "soggiorno e bagno") == (3, True)   # guessed: rooms - 1
    assert parse.bedrooms_from(4, "due camere") == (2, False)          # stated wins
    assert parse.bedrooms_from(None, "") == (None, False)


@pytest.mark.parametrize("text, m2", [
    ("95 m²", 95), ("circa 120 mq", 120), ("1.200 mq", 1200), ("95,5 mq", 95.5),
    ("terreno di 15.000 mq", None),  # land, not a home
    ("nessuna misura", None),
])
def test_m2_in(text, m2):
    assert parse.m2_in(text) == m2


def test_price_in():
    assert parse.price_in("30.000 €") == 30000
    assert parse.price_in("14.681,50 €") == 14681
    assert parse.price_in("Trattativa riservata") is None


@pytest.mark.parametrize("title, town", [
    ("Appartamento all'asta ad Asti corso Alessandria", "Asti"),
    ("Casa Indipendente a Berzano di San Pietro via Roma, 1", "Berzano di San Pietro"),
    ("Villetta a schiera a Bra", "Bra"),
    ("Appartamento all'asta a Isola d'Asti via valle tanaro", "Isola d'Asti"),
    ("Appartamento a Montoggio montoggio", "Montoggio"),
    ("Appartamento a Millesimo santuario del deserto", "Millesimo"),
    ("Casa a Santo Stefano al Mare Via Roma", "Santo Stefano al Mare"),
    ("Appartamento all'asta a Viale vicolo e. Barosso", "Viale"),  # a town called Viale
    ("Appartamento", None),
])
def test_town_in_title(title, town):
    assert parse.town_in_title(title) == town
