"""Reading facts out of Italian listing text: kind of property, bedrooms, m², town.

Sites state these differently, or only in the description, so each source
uses these helpers to fill the same fields.
"""

import re

NUMBER_WORDS = {"una": 1, "un": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6}
ROOM_WORDS = {"monolocale": 1, "bilocale": 2, "trilocale": 3, "quadrilocale": 4, "pentalocale": 5}

# Checked in this order; the first word found decides
APARTMENT_WORDS = ["appartamento", "attico", "mansarda", "loft", "alloggio", *ROOM_WORDS]
HOUSE_WORDS = ["casa", "villa", "villetta", "rustico", "casale", "cascina", "baita", "porzione",
               "terratetto", "terra-tetto", "da terra a cielo", "da terra a tetto", "fabbricato",
               "indipendente", "schiera", "rudere"]
OTHER_WORDS = ["garage", "box", "posto auto", "terreno", "magazzino", "negozio", "ufficio",
               "capannone", "laboratorio", "cantina", "locale commerciale"]

STREET_WORDS = {"via", "viale", "corso", "piazza", "piazzale", "vicolo", "strada", "str.", "borgata",
                "frazione", "fraz.", "località", "loc.", "regione", "reg.", "contrada", "largo"}
# Small words inside town names: "Berzano di San Pietro", "Santo Stefano al Mare"
TOWN_JOINERS = {"di", "de", "del", "della", "dello", "dei", "degli", "delle", "da", "al", "alla", "allo",
                "sul", "sulla", "in", "e", "sopra", "sotto"}


def kind_of(text: str) -> str:
    """apartment, house or other: by the first property word in the text (e.g. a title)."""
    text = text.lower()
    found = [(text.find(word), kind)
             for kind, words in (("apartment", APARTMENT_WORDS), ("house", HOUSE_WORDS), ("other", OTHER_WORDS))
             for word in words if word in text]
    return min(found)[1] if found else "other"


def number(text: str) -> int | None:
    text = text.lower()
    return int(text) if text.isdigit() else NUMBER_WORDS.get(text)


def bedrooms_in(text: str) -> int | None:
    """Bedrooms the text states: "tre camere", "2 camere da letto", "camera da letto"..."""
    text = text.lower()
    match = re.search(r"\b(\d|una|un|due|tre|quattro|cinque|sei)\s*camer[ae]\b", text)
    if match:
        return number(match.group(1))
    singles = len(re.findall(r"\bcamera\b", text))  # "camera, cameretta, bagno": count each one
    return singles or None


def rooms_in(text: str) -> int | None:
    """Rooms ("locali") the text states: "4 locali", "trilocale"..."""
    text = text.lower()
    match = re.search(r"\b(\d+)\s*local[ei]\b", text)
    if match:
        return int(match.group(1))
    return next((n for word, n in ROOM_WORDS.items() if word in text), None)


def m2_in(text: str) -> float | None:
    """Size the text states: "95 m²", "circa 120 mq", "80 metri quadri"."""
    match = re.search(r"(\d{1,4}(?:[.,]\d+)?)\s*(?:mq|m²|m2|metri quadr)", text.lower())
    if not match:
        return None
    digits = match.group(1)
    if re.fullmatch(r"\d{1,3}\.\d{3}", digits):  # "1.200": a thousands dot
        digits = digits.replace(".", "")
    m2 = float(digits.replace(",", "."))  # "95,5": a decimal comma
    return m2 if 15 <= m2 <= 3000 else None  # anything else is land, or a typo


def price_in(text: str) -> float | None:
    """'30.000 €' -> 30000.0; 'Trattativa riservata' -> None"""
    digits = re.sub(r"[^\d,]", "", text).split(",")[0]
    return float(digits) if digits else None


def bedrooms_from(rooms: int | None, text: str) -> tuple[int | None, bool]:
    """(bedrooms, guessed): stated in the text, or worked out from rooms.

    Italian "locali" count the living room too, so 3 locali usually means
    2 bedrooms (a trilocale). It's a guess: sometimes the kitchen counts as well.
    """
    stated = bedrooms_in(text)
    if stated:
        return stated, False
    if rooms:
        return max(rooms - 1, 0), True
    return None, False


def town_in_title(title: str) -> str | None:
    """Town from a title like 'Appartamento all'asta ad Asti corso Alessandria'.

    The town follows "a", "ad" or "in" and starts with a capital letter
    ("Villetta a schiera a Bra": the lowercase "schiera" is skipped). It goes on
    while words are capitalised ("Monte San Savino") or small joining words
    before a capitalised one ("Berzano di San Pietro", "Isola d'Asti"), and stops
    at a street ("corso Alessandria", "Via Roma") or any other word.
    """
    match = re.search(r"\s(?:a|ad|in)\s+([A-ZÀ-Ý].*)$", title)
    if not match:
        return None
    words = match.group(1).replace(",", " ").split()
    town = [words[0]]
    for i, word in enumerate(words[1:], start=1):
        following = words[i + 1] if i + 1 < len(words) else ""
        if word.lower() in STREET_WORDS:
            break
        if word[0].isupper() or re.match(r"(d|dell|sull|all)'[A-ZÀ-Ý]", word):
            town.append(word)
        elif word in TOWN_JOINERS and following[:1].isupper() and following.lower() not in STREET_WORDS:
            town.append(word)
        else:
            break
    return " ".join(town)


def has_any(text: str, words: list[str]) -> list[str]:
    """Which of `words` appear in `text`, ignoring case."""
    text = text.lower()
    return [word for word in words if word.lower() in text]
