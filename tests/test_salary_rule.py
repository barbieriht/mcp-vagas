"""Regra da pretensão (salary_rule): como o valor a informar sai do valor de mercado."""

from datetime import datetime, timezone

import pytest

from vagas.db import connect
from vagas.repo import Repo, VagasError
from vagas.salary import SalaryStore

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
KEY = {"role_key": "data_scientist", "seniority": "senior", "currency": "BRL"}
NOW = lambda: T0.isoformat(timespec="seconds")  # noqa: E731

# Três fontes de mercado: valores 16.000 (média), 20.500 e 28.500 (pontos médios das faixas).
SOURCES = [
    {"source": "glassdoor", "period": "mes", "contract": "clt", "min_value": 13600, "avg_value": 16000,
     "max_value": 19200},
    {"source": "robert half", "period": "mes", "contract": "clt", "min_value": 16000, "max_value": 25000},
    {"source": "linkedin", "period": "mes", "contract": "clt", "min_value": 22000, "max_value": 35000},
]


@pytest.fixture
def conn(db_path, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    c = connect(db_path)
    yield c
    c.close()


def store(conn, rule="teto"):
    return SalaryStore(conn, now=NOW, rule=rule)


def market(conn, points=SOURCES):
    return store(conn).save_salary_estimate(**KEY, points=points)


def evaluate(conn, rule="teto", **overrides):
    args = {"contract": "clt", "my_min": 10500, **overrides}
    return store(conn, rule).evaluate_salary(**KEY, **args)


@pytest.mark.parametrize("rule, value", [
    ("teto", 20500),          # mediana do mercado
    ("meio_termo", 15500),    # (10.500 + 20.500) / 2
    ("percentil_25", 18200),  # quartil inferior (18.250), arredondado
    ("ponto_baixo", 16000),   # mediana de 16.000 (média), 16.000 e 22.000 (mínimos das faixas)
])
def test_rule_defines_the_ask_from_the_same_market_value(conn, rule, value):
    market(conn)

    result = evaluate(conn, rule)

    assert result["decision"] == "aplicar" and result["median"] == 20500
    assert (result["rule"], result["value_to_inform"]) == (rule, value)


def test_unknown_rule_is_rejected(conn):
    with pytest.raises(VagasError, match="meio_termo"):
        store(conn, "media")


def test_ceiling_caps_the_ask_without_excluding_the_job(conn):
    market(conn)

    result = evaluate(conn, "teto", my_max=15000)

    assert result["decision"] == "aplicar" and result["value_to_inform"] == 15000
    assert result["capped"] is True and "teto" in result["reason"]


def test_ask_is_never_below_the_minimum(conn):
    market(conn, [{"source": "glassdoor", "period": "mes", "contract": "clt", "avg_value": 11000}])

    result = evaluate(conn, "meio_termo")

    assert result["value_to_inform"] == 10800  # (10.500 + 11.000) / 2 = 10.750, arredondado sem ficar abaixo


@pytest.mark.parametrize("rule, value", [
    ("teto", 15000), ("meio_termo", 12800), ("percentil_25", 13500), ("ponto_baixo", 12000),
])
def test_published_range_follows_the_rule_but_never_goes_below_its_floor(conn, rule, value):
    app = Repo(conn).add_application(company="Nubank", role="Cientista de Dados", source="linkedin")["application"]
    store(conn).save_salary_estimate(**KEY, company="Nubank", application_id=app["id"], points=[
        {"source": "vaga", "period": "mes", "contract": "clt", "min_value": 12000, "max_value": 18000}])

    result = evaluate(conn, rule, company="Nubank", application_id=app["id"])

    assert result["basis"] == "vaga" and result["value_to_inform"] == value


def test_evaluation_is_saved_in_the_application_columns(conn):
    repo = Repo(conn)
    app = repo.add_application(company="Acme", role="Cientista de Dados Sênior", source="linkedin",
                               work_mode="remoto")["application"]
    market(conn)

    evaluate(conn, "meio_termo", application_id=app["id"])
    saved = repo.get(app["id"])

    assert (saved["salary_basis"], saved["salary_market"], saved["salary_rule"], saved["salary_ask"]) == (
        "mercado", 20500, "meio_termo", 15500)
    assert saved["salary_evaluation"]["inputs"] == {**KEY, "contract": "clt"}


def test_without_data_the_ask_is_the_minimum(conn):
    repo = Repo(conn)
    app = repo.add_application(company="Acme", role="DS", source="linkedin")["application"]
    market(conn, [])

    evaluate(conn, "teto", application_id=app["id"])
    saved = repo.get(app["id"])

    assert (saved["salary_basis"], saved["salary_market"], saved["salary_rule"], saved["salary_ask"]) == (
        "sem_dados", None, "minimo", 10500)


def test_reevaluation_applies_the_current_rule_to_registered_jobs(conn, tmp_path):
    policy = tmp_path / "politica.md"
    policy.write_text("- Remoto nacional (BRL, CLT): mínimo 10.500\n", encoding="utf-8")
    repo = Repo(conn)
    app = repo.add_application(company="Acme", role="Cientista de Dados Sênior", source="linkedin",
                               work_mode="remoto", seniority="senior", status="a_aplicar")["application"]
    market(conn)
    SalaryStore(conn, now=NOW, policy_path=policy).evaluate_salary(**KEY, contract="clt", application_id=app["id"])

    result = SalaryStore(conn, now=NOW, policy_path=policy, rule="meio_termo").reevaluate_applications()

    assert result["reevaluated"] == 1
    assert result["changed"] == [{
        "id": app["id"], "company": "Acme", "role": "Cientista de Dados Sênior", "url": None,
        "decision": "aplicar", "salary_market": 20500, "before": 20500, "after": 15500}]
    assert repo.get(app["id"])["salary_ask"] == 15500


def test_reevaluation_infers_the_inputs_of_older_evaluations(conn, tmp_path):
    policy = tmp_path / "politica.md"
    policy.write_text("- Remoto nacional (BRL, CLT): mínimo 10.500\n", encoding="utf-8")
    repo = Repo(conn)
    app = repo.add_application(company="Acme", role="Cientista de Dados Sênior", source="linkedin",
                               work_mode="remoto", seniority="senior", status="a_aplicar")["application"]
    market(conn)
    old = '{"decision": "aplicar", "value_to_inform": 20500, "contract": "clt", "reason": "Mediana BRL 20.500"}'
    with conn:
        conn.execute("UPDATE applications SET salary_evaluation = ? WHERE id = ?", (old, app["id"]))

    result = SalaryStore(conn, now=NOW, policy_path=policy, rule="meio_termo").reevaluate_applications()

    assert result["reevaluated"] == 1 and repo.get(app["id"])["salary_ask"] == 15500


def test_discarded_research_is_ignored(conn):
    saved = market(conn)

    store(conn).discard_salary_estimate(saved["search_id"], "matéria jornalística, não é pesquisa salarial")
    found = store(conn).find_salary_estimate(**KEY)

    assert found["points"] == [] and found["fresh_market"] is False
    assert evaluate(conn)["decision"] == "pesquisar"


def test_found_points_carry_the_search_id(conn):
    saved = market(conn)

    found = store(conn).find_salary_estimate(**KEY)

    assert {p["search_id"] for p in found["points"]} == {saved["search_id"]}


def test_discarding_an_unknown_search_is_a_clear_error(conn):
    with pytest.raises(VagasError, match="999"):
        store(conn).discard_salary_estimate(999, "teste")
