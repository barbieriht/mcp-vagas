import pytest
from mcp import Client

from vagas.db import connect
from vagas.repo import Repo
from vagas.salary import SalaryStore, research_queries
from vagas.server import build_server

pytestmark = pytest.mark.anyio

POLICY = "- Modo: minimo\n- Remoto nacional (BRL, CLT): mínimo 8000\n- Híbrido em São Paulo (BRL, CLT): mínimo 10000\n"


def test_queries_go_from_job_and_company_to_market():
    queries = research_queries("Cientista de Dados Sênior - Search Platform IT | REF#123", "Mercado Livre Brasil",
                               "São Paulo, São Paulo, Brazil", "data_scientist", "senior")

    assert queries == [
        'salário "Cientista de Dados Sênior" Mercado Livre Brasil São Paulo',
        'salário "Cientista de Dados Sênior" Mercado Livre Brasil',
        "Mercado Livre Brasil data scientist salary Brazil levels.fyi",
        "salário cientista de dados sênior São Paulo",
        "salário cientista de dados sênior Brasil",
    ]


def test_queries_without_company_or_city():
    queries = research_queries("Senior Data Scientist", None, "Brazil", "data_scientist", "senior")

    assert queries == ["salário cientista de dados sênior Brasil"]
    assert research_queries("AI Engineer", "Acme", None, "ai_engineer", None)[-1] == "salário engenheiro de ia Brasil"


@pytest.fixture
def store(db_path, tmp_path, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    policy = tmp_path / "politica-salarial.md"
    policy.write_text(POLICY, encoding="utf-8")
    conn = connect(db_path)
    yield SalaryStore(conn, policy_path=policy), Repo(conn)
    conn.close()


def test_evaluation_without_data_brings_the_queries(store):
    salaries, repo = store
    app = repo.add_application(company="Danone", role="Cientista de Dados Sênior", source="linkedin",
                               work_mode="hibrido", location="São Paulo, SP", status="a_aplicar")["application"]

    result = salaries.evaluate_salary("data_scientist", "senior", "BRL", "clt", company="Danone",
                                      application_id=app["id"])

    assert result["decision"] == "pesquisar"
    assert result["research_queries"][0] == 'salário "Cientista de Dados Sênior" Danone São Paulo'


def test_company_without_data_still_brings_company_queries(store):
    salaries, repo = store
    app = repo.add_application(company="Danone", role="Cientista de Dados Sênior", source="linkedin",
                               work_mode="remoto", status="a_aplicar")["application"]
    salaries.save_salary_estimate("data_scientist", "senior", "BRL", [
        {"source": "guia", "period": "mes", "avg_value": 15000}])

    result = salaries.evaluate_salary("data_scientist", "senior", "BRL", "clt", company="Danone",
                                      application_id=app["id"])
    salaries.save_salary_estimate("data_scientist", "senior", "BRL", [], company="Danone")
    after = salaries.evaluate_salary("data_scientist", "senior", "BRL", "clt", company="Danone",
                                     application_id=app["id"])

    assert result["needs_research"] is True and "Danone" in result["research_queries"][0]
    assert after["needs_research"] is False and after["research_queries"] == []


async def test_triage_and_tool_docs_point_to_the_queries(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert "research_queries" in tools["evaluate_salary"].description
    assert "research_queries" in tools["triage_job"].description
