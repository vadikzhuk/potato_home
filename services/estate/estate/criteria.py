"""criteria.yaml: what to look for and how to rank it.

It is read again every time it's needed, so saving the file is all it takes.
check() catches typos with a clear message instead of a crash later on.
"""

import os
import re
from pathlib import Path

import yaml

from .core import SCORE_PARTS, Invalid
from .sources import REGIONS

SERVICE_DIR = Path(__file__).resolve().parent.parent  # services/estate when run from the repo
KINDS = ("apartment", "house", "other")


def path() -> Path:
    return Path(os.environ.get("ESTATE_CRITERIA") or SERVICE_DIR / "criteria.yaml")


def load(file: Path | None = None) -> dict:
    file = file or path()
    try:
        criteria = yaml.safe_load(file.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise Invalid(f"Can't read {file.name}: {error}") from None
    check(criteria)
    return criteria


def check(criteria: dict) -> None:
    """Raise Invalid with everything that's wrong, if anything is."""
    try:
        search, scoring = criteria["search"], criteria["scoring"]
        digest, fetch = criteria["digest"], criteria["fetch"]
        numbers = {
            "search.min_price": search["min_price"], "search.max_price": search["max_price"],
            "search.bedrooms.min": search["bedrooms"]["min"], "search.bedrooms.max": search["bedrooms"]["max"],
            "scoring.preferred_bonus": scoring["preferred_bonus"],
            **{f"scoring.weights.{part}": weight for part, weight in scoring["weights"].items()},
            **{f"digest.{key}": digest[key] for key in ("top", "auctions", "min_score")},
            **{f"fetch.{key}": fetch[key] for key in ("pause_seconds", "gone_after_days")},
        }
        lists = {
            "search.regions": search["regions"], "search.kinds": search["kinds"],
            "exclude_words": criteria["exclude_words"],
            **{f"scoring.{key}": scoring[key]
               for key in ("good_condition", "bad_condition", "extras", "preferred_provinces")},
        }
    except (KeyError, TypeError) as error:
        raise Invalid(f"criteria.yaml is missing {error} (compare with the file in the repository)") from None

    problems = [f"{name} must be a number" for name, value in numbers.items() if not isinstance(value, (int, float))]
    problems += [f"{name} must be a list, like [a, b]" for name, value in lists.items() if not isinstance(value, list)]
    if problems:
        raise Invalid("criteria.yaml: " + "; ".join(problems))

    problems += [f"unknown region {r!r} (known: {', '.join(REGIONS)})" for r in search["regions"] if r not in REGIONS]
    problems += [f"unknown kind {k!r} (known: {', '.join(KINDS)})" for k in search["kinds"] if k not in KINDS]
    problems += [f"unknown weight {p!r} (known: {', '.join(SCORE_PARTS)})"
                 for p in scoring["weights"] if p not in SCORE_PARTS]
    if not 0 <= search["min_price"] <= search["max_price"]:
        problems.append("min_price must be between 0 and max_price")
    if search["bedrooms"]["min"] > search["bedrooms"]["max"]:
        problems.append("bedrooms: min is bigger than max")
    if sum(scoring["weights"].values()) <= 0:
        problems.append("weights add up to 0")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(fetch["time"])):
        problems.append('fetch.time must look like "05:00"')
    if problems:
        raise Invalid("criteria.yaml: " + "; ".join(problems))
