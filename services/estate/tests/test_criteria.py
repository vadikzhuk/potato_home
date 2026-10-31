import pytest

from estate import criteria
from estate.core import Invalid

from helpers import criteria as make_criteria


def test_the_repository_file_is_valid():
    criteria.load()  # services/estate/criteria.yaml


def test_typos_are_explained():
    with pytest.raises(Invalid, match="unknown region 'Piedmont'"):
        criteria.check(make_criteria(search={"regions": ["Piedmont"]}))
    with pytest.raises(Invalid, match="unknown weight 'size'"):
        criteria.check(make_criteria(scoring={**make_criteria()["scoring"], "weights": {"size": 1}}))
    with pytest.raises(Invalid, match="search.max_price must be a number"):
        criteria.check(make_criteria(search={"max_price": "30k"}))
    with pytest.raises(Invalid, match="fetch.time"):
        criteria.check(make_criteria(fetch={"time": "5am"}))
    broken = make_criteria()
    del broken["digest"]
    with pytest.raises(Invalid, match="missing 'digest'"):
        criteria.check(broken)
