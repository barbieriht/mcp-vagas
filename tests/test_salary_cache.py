from datetime import datetime, timedelta, timezone

import pytest

from vagas.db import connect
from vagas.repo import VagasError
from vagas.salary import SalaryStore

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
KEY = {"role_key": "data_scientist", "seniority": "pleno", "currency": "BRL"}


class Clock:
    def __init__(self):
        self.at = T0

    def __call__(self):
        return self.at.isoformat(timespec="seconds")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def store(conn, clock, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    return SalaryStore(conn, now=clock)


def point(source="glassdoor", **values):
    return {"source": source, "source_url": f"https://{source}.example/x", "period": "mes",
            "contract": "clt", **values}


def test_saves_and_finds_company_and_market_separately(store):
    store.save_salary_estimate(**KEY, company="Nubank", points=[point(avg_value=12000)])
    store.save_salary_estimate(**KEY, points=[point("linkedin", avg_value=10000)])

    found = store.find_salary_estimate(**KEY, company="Nubank")

    assert found["company"]["median"] == 12000
    assert found["market"]["median"] == 10000
    assert (found["fresh_company"], found["fresh_market"]) == (True, True)
    assert {(p["scope"], p["source"]) for p in found["points"]} == {("company", "glassdoor"), ("market", "linkedin")}
    assert found["points"][0]["source_url"].startswith("https://")


def test_without_company_only_market_is_returned(store):
    store.save_salary_estimate(**KEY, points=[point(avg_value=10000)])

    found = store.find_salary_estimate(**KEY)

    assert found["company"] is None and found["fresh_company"] is False
    assert found["market"]["median"] == 10000


def test_nothing_saved_means_not_fresh(store):
    found = store.find_salary_estimate(**KEY, company="Nubank")

    assert found == {"company": None, "market": None, "fresh_company": False, "fresh_market": False, "points": []}


def test_company_name_variants_share_cache(store):
    store.save_salary_estimate(**KEY, company="Nubank S.A.", points=[point(avg_value=12000)])

    assert store.find_salary_estimate(**KEY, company="nubank")["company"]["median"] == 12000


@pytest.mark.parametrize("other", [
    {"role_key": "ml_engineer"}, {"seniority": "senior"}, {"currency": "USD"},
])
def test_key_parts_never_mix(store, other):
    store.save_salary_estimate(**KEY, points=[point(avg_value=10000)])

    assert store.find_salary_estimate(**{**KEY, **other})["market"] is None


def test_fresh_until_ttl_then_stale(store, clock):
    store.save_salary_estimate(**KEY, points=[point(avg_value=10000)])

    clock.at = T0 + timedelta(days=90)
    assert store.find_salary_estimate(**KEY)["fresh_market"] is True

    clock.at = T0 + timedelta(days=90, seconds=1)
    found = store.find_salary_estimate(**KEY)
    assert found["fresh_market"] is False
    assert found["market"] is None
    assert found["points"][0]["fresh"] is False


def test_ttl_is_configurable(conn, clock, monkeypatch):
    monkeypatch.setenv("VAGAS_SALARY_TTL_DAYS", "30")
    store = SalaryStore(conn, now=clock)
    store.save_salary_estimate(**KEY, points=[point(avg_value=10000)])

    clock.at = T0 + timedelta(days=31)

    assert store.find_salary_estimate(**KEY)["fresh_market"] is False


def test_empty_search_is_fresh_and_says_nothing_was_found(store):
    store.save_salary_estimate(**KEY, company="Startup X", points=[], note="Nada no Glassdoor nem LinkedIn")

    found = store.find_salary_estimate(**KEY, company="Startup X")

    assert found["fresh_company"] is True
    assert found["company"] == {"points": 0, "sources": 0, "median": None, "min": None, "max": None,
                                "confidence": None, "nothing_found": True,
                                "searched_at": T0.isoformat(timespec="seconds"),
                                "notes": ["Nada no Glassdoor nem LinkedIn"]}


def test_newer_fresh_search_adds_to_older_fresh_one(store, clock):
    store.save_salary_estimate(**KEY, points=[point("glassdoor", avg_value=10000)])
    clock.at = T0 + timedelta(days=10)
    store.save_salary_estimate(**KEY, points=[point("linkedin", avg_value=12000)])

    market = store.find_salary_estimate(**KEY)["market"]

    assert (market["points"], market["median"]) == (2, 11000)
    assert market["searched_at"] == clock()


def test_median_resists_outlier_and_counts_sources(store):
    store.save_salary_estimate(**KEY, points=[
        point("glassdoor", avg_value=10000), point("glassdoor", avg_value=11000),
        point("linkedin", avg_value=12000), point("guia", avg_value=95000),
    ])

    market = store.find_salary_estimate(**KEY)["market"]

    assert market["median"] == 11500
    assert (market["min"], market["max"]) == (10000, 95000)
    assert (market["sources"], market["confidence"]) == (3, "alta")


@pytest.mark.parametrize("sources, confidence", [(["a"], "baixa"), (["a", "b"], "media"), (["a", "b", "c"], "alta")])
def test_confidence_by_distinct_sources(store, sources, confidence):
    store.save_salary_estimate(**KEY, points=[point(s, avg_value=10000) for s in sources + sources])

    assert store.find_salary_estimate(**KEY)["market"]["confidence"] == confidence


@pytest.mark.parametrize("values, monthly", [
    ({"avg_value": 10000}, 10000),
    ({"min_value": 8000, "max_value": 12000}, 10000),
    ({"min_value": 9000}, 9000),
    ({"max_value": 11000}, 11000),
])
def test_point_value_prefers_average_then_midpoint(store, values, monthly):
    store.save_salary_estimate(**KEY, points=[point(**values)])

    assert store.find_salary_estimate(**KEY)["market"]["median"] == monthly


@pytest.mark.parametrize("period, contract, currency, raw, monthly", [
    ("ano", "clt", "BRL", 133300, 10000),
    ("ano", "pj", "BRL", 120000, 10000),
    ("ano", "desconhecido", "BRL", 120000, 10000),
    ("ano", "clt", "USD", 60000, 5000),
    ("hora", "pj", "BRL", 100, 16000),
    ("mes", "pj", "BRL", 15000, 15000),
])
def test_conversion_to_monthly(store, period, contract, currency, raw, monthly):
    key = {**KEY, "currency": currency}
    store.save_salary_estimate(**key, points=[{"source": "x", "period": period, "contract": contract, "avg_value": raw}])

    found = store.find_salary_estimate(**key)

    assert found["market"]["median"] == monthly
    assert found["points"][0]["monthly_value"] == monthly
    assert found["points"][0]["avg_value"] == raw


@pytest.mark.parametrize("bad, message", [
    (point(), "min_value"),
    (point(avg_value=-1), "avg_value"),
    (point(min_value=12000, max_value=8000), "min_value"),
    (point(min_value=10000, avg_value=9000, max_value=12000), "avg_value"),
    ({**point(avg_value=1), "period": "semana"}, "period"),
    ({**point(avg_value=1), "contract": "estagio"}, "contract"),
    ({**point(avg_value=1), "salario": 1}, "salario"),
])
def test_invalid_points_are_rejected(store, bad, message):
    with pytest.raises(VagasError, match=message):
        store.save_salary_estimate(**KEY, points=[bad])
    assert store.find_salary_estimate(**KEY)["market"] is None


@pytest.mark.parametrize("field, value", [
    ("role_key", "cientista"), ("seniority", "sr"), ("currency", "GBP"),
])
def test_invalid_key_is_rejected(store, field, value):
    with pytest.raises(VagasError, match=field):
        store.save_salary_estimate(**{**KEY, field: value}, points=[])
    with pytest.raises(VagasError, match=field):
        store.find_salary_estimate(**{**KEY, field: value})
