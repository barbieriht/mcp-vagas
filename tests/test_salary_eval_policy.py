import json

import pytest
from mcp import Client

from vagas.db import connect
from vagas.repo import Repo, VagasError
from vagas.salary import SalaryStore
from vagas.server import build_server

KEY = {"role_key": "data_scientist", "seniority": "pleno"}
POLICY = """\
- Modo: minimo
- Multiplicador PJ: 1.4
- Remoto nacional (BRL, CLT): mínimo 8.000, máximo 12.000
- Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10.000
- Internacional (USD): mínimo 3.000
"""


@pytest.fixture
def policy_path(tmp_path):
    path = tmp_path / "politica-salarial.md"
    path.write_text(POLICY, encoding="utf-8")
    return path


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def store(conn, policy_path, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    return SalaryStore(conn, policy_path=policy_path)


def market(store, value, currency="BRL", contract="clt"):
    store.save_salary_estimate(**KEY, currency=currency, points=[
        {"source": "glassdoor", "period": "mes", "contract": contract, "avg_value": value}])


def test_band_is_chosen_by_work_mode_and_location(store):
    market(store, 9000)

    remote = store.evaluate_salary(**KEY, currency="BRL", contract="clt", work_mode="remoto")
    sp = store.evaluate_salary(**KEY, currency="BRL", contract="clt", work_mode="hibrido", location="São Paulo, SP")

    assert (remote["decision"], remote["value_to_inform"]) == ("aplicar", 9000)
    assert remote["policy"] == {"band": "Remoto nacional", "mode": "minimo", "my_min": 8000, "my_max": 12000,
                                "pj_multiplier": 1.4}
    assert sp["decision"] == "nao_aplicar" and "10.000" in sp["reason"]
    assert sp["policy"]["band"] == "Híbrido/presencial em São Paulo e região"


def test_pj_job_uses_policy_multiplier(store):
    market(store, 13000, contract="pj")

    result = store.evaluate_salary(**KEY, currency="BRL", contract="pj", work_mode="remoto")

    assert (result["decision"], result["contract"], result["value_to_inform"]) == ("aplicar", "pj", 13000)
    assert "11.200" in result["reason"]  # 8.000 x 1.4


def test_band_without_clt_is_not_multiplied_for_pj(store):
    market(store, 3200, currency="USD", contract="pj")

    result = store.evaluate_salary(**KEY, currency="USD", contract="pj", work_mode="remoto", location="Lisboa")

    assert (result["decision"], result["value_to_inform"]) == ("aplicar", 3200)
    assert result["policy"]["band"] == "Internacional"


def test_work_mode_and_location_come_from_the_application(store, conn):
    app = Repo(conn).add_application(company="Acme", role="DS", source="gupy", work_mode="presencial",
                                     location="São Paulo - SP", status="a_aplicar")["application"]
    market(store, 9000)

    result = store.evaluate_salary(**KEY, currency="BRL", contract="clt", application_id=app["id"])
    saved = json.loads(conn.execute("SELECT salary_evaluation FROM applications WHERE id = ?",
                                    (app["id"],)).fetchone()[0])

    assert result["decision"] == "nao_aplicar"
    assert saved["policy"]["band"] == "Híbrido/presencial em São Paulo e região"


def test_explicit_values_still_win_over_the_policy(store):
    market(store, 9000)

    result = store.evaluate_salary(**KEY, currency="BRL", contract="clt", my_min=9500, work_mode="remoto")

    assert result["decision"] == "nao_aplicar"
    assert result["policy"] == {"band": None, "mode": "minimo", "my_min": 9500, "my_max": None,
                                "pj_multiplier": None}


def test_explicit_mode_overrides_policy_mode(store):
    market(store, 13000)

    result = store.evaluate_salary(**KEY, currency="BRL", contract="clt", work_mode="remoto", mode="faixa")

    assert result["decision"] == "nao_aplicar" and "12.000" in result["reason"]


def test_without_my_min_nor_work_mode_is_a_clear_error(store):
    with pytest.raises(VagasError, match="work_mode"):
        store.evaluate_salary(**KEY, currency="BRL", contract="clt")


def test_missing_policy_file_is_a_clear_error(conn, tmp_path):
    store = SalaryStore(conn, policy_path=tmp_path / "nada.md")

    with pytest.raises(VagasError, match="não encontrada"):
        store.evaluate_salary(**KEY, currency="BRL", contract="clt", work_mode="remoto")


def test_unfilled_policy_is_a_clear_error(conn, policy_path):
    policy_path.write_text("- Multiplicador PJ: <PREENCHER>\n", encoding="utf-8")

    with pytest.raises(VagasError, match="PREENCHER"):
        SalaryStore(conn, policy_path=policy_path).evaluate_salary(
            **KEY, currency="BRL", contract="clt", work_mode="remoto")


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content


@pytest.mark.anyio
async def test_evaluate_salary_reads_the_policy_via_mcp(db_path, policy_path, monkeypatch):
    monkeypatch.setenv("VAGAS_SALARY_POLICY", str(policy_path))
    async with Client(build_server(db_path)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        await client.call_tool("save_salary_estimate", {**KEY, "currency": "BRL", "points": [
            {"source": "glassdoor", "period": "mes", "contract": "clt", "avg_value": 9000}]})
        result = payload(await client.call_tool("evaluate_salary", {
            **KEY, "currency": "BRL", "contract": "clt", "work_mode": "remoto"}))
        uncovered = await client.call_tool("evaluate_salary", {
            **KEY, "currency": "BRL", "contract": "clt", "work_mode": "hibrido", "location": "Recife"})

    schema = tools["evaluate_salary"].input_schema
    assert "my_min" not in schema.get("required", [])
    assert "work_mode" in schema["properties"] and "presencial" in json.dumps(schema)
    assert "politica-salarial" in tools["evaluate_salary"].description
    assert (result["decision"], result["policy"]["band"]) == ("aplicar", "Remoto nacional")
    assert uncovered.is_error and "Recife" in uncovered.content[0].text
