from datetime import datetime, timedelta, timezone

import pytest

from vagas.db import connect
from vagas.repo import VagasError
from vagas.salary import SalaryStore

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
KEY = {"role_key": "data_scientist", "seniority": "pleno", "currency": "BRL"}
POLICY = {"my_min": 10000, "my_max": 14000, "pj_multiplier": 1.4}


class Clock:
    def __init__(self):
        self.at = T0

    def __call__(self):
        return self.at.isoformat(timespec="seconds")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(db_path, clock, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    conn = connect(db_path)
    yield SalaryStore(conn, now=clock)
    conn.close()


def market(store, *values, contract="clt", source="glassdoor"):
    store.save_salary_estimate(**KEY, points=[
        {"source": f"{source}{i}", "period": "mes", "contract": contract, "avg_value": v} for i, v in enumerate(values)
    ])


def company(store, *values, contract="clt"):
    store.save_salary_estimate(**KEY, company="Nubank", points=[
        {"source": "glassdoor", "period": "mes", "contract": contract, "avg_value": v} for v in values
    ])


def evaluate(store, contract="clt", **overrides):
    return store.evaluate_salary(**KEY, contract=contract, **{**POLICY, **overrides})


@pytest.mark.parametrize("mode, median, my_max, decision, value", [
    ("minimo", 12000, 14000, "aplicar", 12000),
    ("minimo", 10000, 14000, "aplicar", 10000),
    ("minimo", 9000, 14000, "nao_aplicar", None),
    ("minimo", 20000, 14000, "aplicar", 14000),
    ("minimo", 20000, None, "aplicar", 20000),
    ("faixa", 12000, 14000, "aplicar", 12000),
    ("faixa", 14000, 14000, "aplicar", 14000),
    ("faixa", 20000, 14000, "nao_aplicar", None),
    ("faixa", 9000, 14000, "nao_aplicar", None),
])
def test_decision_and_value_by_mode(store, mode, median, my_max, decision, value):
    market(store, median)

    result = evaluate(store, mode=mode, my_max=my_max)

    assert (result["decision"], result["value_to_inform"]) == (decision, value)
    assert result["basis"] == "mercado"
    assert result["median"] == median


def test_reason_shows_the_numbers_compared(store):
    market(store, 9000)

    reason = evaluate(store)["reason"]

    assert "9.000" in reason and "10.000" in reason


def test_reason_for_range_mode_above(store):
    market(store, 20000)

    assert "acima" in evaluate(store, mode="faixa")["reason"]


def test_range_mode_requires_max(store):
    market(store, 12000)

    with pytest.raises(VagasError, match="my_max"):
        evaluate(store, mode="faixa", my_max=None)


def test_company_data_takes_priority_over_market(store):
    market(store, 9000)
    company(store, 13000)

    result = store.evaluate_salary(**KEY, contract="clt", company="Nubank S.A.", **POLICY)

    assert (result["basis"], result["decision"], result["value_to_inform"]) == ("empresa", "aplicar", 13000)
    assert result["needs_research"] is False


def test_market_is_used_when_company_is_unknown_but_research_is_suggested(store):
    market(store, 12000)

    result = store.evaluate_salary(**KEY, contract="clt", company="Nubank", **POLICY)

    assert (result["basis"], result["decision"]) == ("mercado", "aplicar")
    assert result["needs_research"] is True


def test_stale_company_data_is_ignored(store, clock):
    company(store, 13000)
    clock.at = T0 + timedelta(days=91)
    market(store, 11000)

    result = store.evaluate_salary(**KEY, contract="clt", company="Nubank", **POLICY)

    assert (result["basis"], result["median"]) == ("mercado", 11000)


def test_nothing_fresh_means_research(store):
    result = evaluate(store)

    assert (result["decision"], result["needs_research"], result["value_to_inform"]) == ("pesquisar", True, None)
    assert result["basis"] is None


def test_fresh_empty_market_search_applies_with_minimum(store):
    store.save_salary_estimate(**KEY, points=[], note="nada encontrado")

    result = evaluate(store)

    assert (result["decision"], result["basis"], result["value_to_inform"]) == ("aplicar", "sem_dados", 10000)
    assert result["needs_research"] is False


def test_fresh_empty_company_search_still_needs_market(store):
    store.save_salary_estimate(**KEY, company="Startup", points=[])

    result = store.evaluate_salary(**KEY, contract="clt", company="Startup", **POLICY)

    assert (result["decision"], result["needs_research"]) == ("pesquisar", True)


@pytest.mark.parametrize("my_min, median, value", [
    (10000, 12345, 12300),
    (10000, 12350, 12400),
    (10010, 10020, 10100),
])
def test_value_is_rounded_to_hundreds_never_below_minimum(store, my_min, median, value):
    market(store, median)

    assert evaluate(store, my_min=my_min, my_max=None)["value_to_inform"] == value


def test_pj_job_scales_my_range_and_converts_clt_points(store):
    market(store, 12000, contract="clt")

    result = evaluate(store, contract="pj")

    assert result["contract"] == "pj"
    assert result["median"] == 16800
    assert (result["decision"], result["value_to_inform"]) == ("aplicar", 16800)


def test_pj_job_below_scaled_minimum_is_rejected(store):
    market(store, 13000, contract="pj")

    result = evaluate(store, contract="pj")

    assert result["decision"] == "nao_aplicar"
    assert "14.000" in result["reason"]


def test_clt_job_converts_pj_points(store):
    market(store, 10000, contract="clt", source="a")
    market(store, 16800, contract="pj", source="b")

    assert evaluate(store)["median"] == 11000


def test_unknown_point_contract_is_taken_as_job_contract(store):
    market(store, 15000, contract="desconhecido")

    result = evaluate(store, contract="pj")

    assert (result["median"], result["decision"]) == (15000, "aplicar")


def test_unknown_job_contract_is_treated_as_clt(store):
    market(store, 12000)

    result = evaluate(store, contract="desconhecido")

    assert (result["contract"], result["value_to_inform"]) == ("clt", 12000)


def test_pj_multiplier_is_required_only_when_converting(store):
    market(store, 12000, contract="clt")

    assert evaluate(store, pj_multiplier=None)["decision"] == "aplicar"
    with pytest.raises(VagasError, match="pj_multiplier"):
        evaluate(store, contract="pj", pj_multiplier=None)


def test_range_sources_and_confidence_come_from_used_points(store):
    market(store, 10000, 12000, 30000)

    result = evaluate(store)

    assert result["range"] == [10000, 30000]
    assert (result["sources"], result["confidence"]) == (3, "alta")


@pytest.mark.parametrize("bad, field", [
    ({"my_min": -1}, "my_min"),
    ({"my_min": 15000, "my_max": 14000}, "my_max"),
    ({"pj_multiplier": 0}, "pj_multiplier"),
    ({"mode": "media"}, "mode"),
])
def test_invalid_policy_is_rejected(store, bad, field):
    market(store, 12000)

    with pytest.raises(VagasError, match=field):
        evaluate(store, **bad)
