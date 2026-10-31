from estate.sources import pvp, trovacasa

CARD = """
<div class="card js_slider_external js_card_immobile">
  <div class="card__img"><img data-src="https://pic.trovacasa.it/image/1/m-c.jpg" src="data:,"></div>
  <div class="card__elementsContainer">
    <a href="/annunci/at-tc-87054-73956135" class="card__title">Appartamento all&#x27;asta ad Asti corso Alessandria</a>
    <span class="card__quartiere">Corso Alessandria</span>
    <div class="card__infoContainer"><span class="card__info">95 m&#xB2;</span><span class="card__info">4 locali</span></div>
    <span class="card__price">30.000 &#x20AC;</span>
    <p class="card__description">Lotto B: soggiorno-cucina, tre camere, bagno, balcone e terrazzo.</p>
    <div class="card__tagContainer"><p class="annuncioTag">Terrazzo</p><p class="annuncioTag">All&#x27;asta/Asta Giudiziaria</p></div>
  </div>
</div>
<a href="/case-in-vendita/provincia-di-asti?PrezzoMax=30000&amp;page=2">2</a>
"""


def test_trovacasa_card():
    [listing] = trovacasa.parse_page(CARD, "Piemonte", "Asti")
    assert listing["source_id"] == "73956135"
    assert listing["url"] == "https://www.trovacasa.it/annunci/at-tc-87054-73956135"
    assert (listing["price"], listing["m2"], listing["rooms"]) == (30000, 95, 4)
    assert (listing["bedrooms"], listing["bedrooms_guessed"]) == (3, False)  # "tre camere" beats 4 - 1
    assert listing["kind"] == "apartment" and listing["is_auction"]
    assert listing["town"] == "Asti" and listing["address"] == "Corso Alessandria"
    assert listing["photo"] == "https://pic.trovacasa.it/image/1/m-c.jpg"
    assert listing["features"] == ["Terrazzo", "All'asta/Asta Giudiziaria"]


def test_trovacasa_next_page():
    assert trovacasa.has_page(CARD, 2)
    assert not trovacasa.has_page(CARD, 3)
    assert not trovacasa.has_page(CARD.replace("page=2", "page=20"), 2)


def lot(**fields):
    data = {
        "id": 4599255, "categoriaBene": ["ABITAZIONE_TIPO_CIV"], "prezzoBaseAsta": 29844.0, "offertaMinima": 22383.0,
        "dataVendita": "2026-12-03", "disponibilita": ["OCCUP"], "immagine": None, "immagineCover": None,
        "descLotto": "Fabbricato costituito da due piani: cucina, soggiorno, tre camere, un bagno; 120 mq.",
        "indirizzo": {"via": "Via Roma 1", "citta": "Silvano d'Orba", "provincia": "Alessandria"},
    }
    data.update(fields)
    return data


def test_pvp_lot():
    listing = pvp.to_listing(lot(), "Piemonte")
    assert listing["url"].endswith("idAnnuncio=4599255")
    assert listing["title"] == "Casa all'asta a Silvano d'Orba"  # "fabbricato" in the text: a house
    assert (listing["price"], listing["m2"], listing["bedrooms"]) == (22383, 120, 3)  # the lowest offer
    assert listing["occupancy"] == "occupied" and listing["auction_date"] == "2026-12-03"
    assert listing["features"] == ["prezzo base 29.844 €"]


def test_pvp_kinds():
    assert pvp.kind_of(lot(categoriaBene=["APPARTAMENTO", "GARAGE_AUTORIMESSA"])) == "apartment"
    assert pvp.kind_of(lot(categoriaBene=["VILLA"])) == "house"
    assert pvp.kind_of(lot(categoriaBene=["ABITAZIONE_TIPO_ECO"], descLotto="Abitazione.")) == "apartment"
    assert pvp.kind_of(lot(categoriaBene=["TERRENO"])) == "other"


def test_pvp_skipped_when_auctions_are_off():
    assert list(pvp.fetch({"auctions": False}, http=None, pause=lambda: None)) == []
