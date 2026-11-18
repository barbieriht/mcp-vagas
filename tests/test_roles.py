"""Cargos alvo em texto livre, sugeridos pelo currículo geral e confirmados pelo usuário; as famílias de dados são só
sinônimos conhecidos. E a senioridade trainee."""

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from test_job_board import Fetcher as BoardFetcher
from test_job_board import board
from test_triage import POLICY, Fetcher, gupy
from vagas import roles
from vagas.db import connect
from vagas.job_posting import classify_role
from vagas.resume_repo import ResumeStore, default_draft_path
from vagas.salary import research_queries
from vagas.server import build_server
from vagas.triage import Triage, parse_criteria

pytestmark = pytest.mark.anyio


# --- catálogo --------------------------------------------------------------------------------------

@pytest.mark.parametrize("item, title, matches", [
    ("Desenvolvedor Backend", "Desenvolvedora Backend Pleno", True),  # gênero e nível não contam
    ("Desenvolvedor Backend", "Pessoa Desenvolvedora Backend Sr. (Java)", True),
    ("Desenvolvedor Backend", "Desenvolvedor Frontend", False),
    ("Desenvolvedor Backend", "Backend Developer", False),  # outra língua: só com sinônimo
    ("Desenvolvedor Backend (Backend Developer)", "Senior Backend Developer", True),
    ("Product Manager (PM, Gerente de Produto)", "Gerente de Produtos III", True),
    ("Product Manager (PM, Gerente de Produto)", "PM de Pagamentos", True),
    ("Engenheiro de Software", "Engenheiras de Software", True),
    ("Analista de Dados", "Analista de BI", True),  # família conhecida: os padrões dela valem
])
def test_free_text_roles_match_titles_by_their_words(item, title, matches):
    assert roles.parse(item).matches(title) is matches


@pytest.mark.parametrize("item, key", [
    ("data_scientist", "data_scientist"), ("Cientista de Dados", "data_scientist"), ("ML Engineer", "ml_engineer"),
    ("machine learning engineer", "ml_engineer"), ("Desenvolvedor Backend", "desenvolvedor_backend"),
    ("Desenvolvedor Backend Sênior", "desenvolvedor_backend"), ("Product Manager (PM)", "product_manager"),
])
def test_known_families_keep_their_keys_and_free_roles_get_a_slug(item, key):
    assert roles.parse(item).key == key


def test_the_users_roles_come_before_the_known_families():
    mine = roles.parse_list("Cientista de Dados de Pesquisa (Research Scientist)")

    assert roles.classify("Cientista de Dados de Pesquisa Pleno", mine).key == "cientista_de_dados_de_pesquisa"
    assert roles.classify("Cientista de Dados Pleno", mine).key == "data_scientist"
    assert roles.classify("Astronauta", mine) is None


def test_suggestions_come_from_the_resume_without_the_level_and_without_repeats():
    resume = fictitious_resume()
    resume["experience"][0]["title_aliases"] = ["Coordenador Técnico de Engenharia de IA"]

    found = roles.suggest_from_resume(resume)

    names = [s["name"] for s in found]
    assert names[0] == resume["experience"][0]["title"]
    assert "Coordenador Técnico de Engenharia de IA" in names
    assert "Data Scientist" in names and not any("Intern" in n for n in names)
    assert len(names) == len({tuple(sorted(roles.parse(n).names)) for n in names})
    assert all(s["from"] for s in found)
    assert roles.suggest_from_resume(None) == []


# --- trainee ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("title, seniority", [
    ("Programa de Trainee 2027 - Dados", "trainee"), ("Trainee em Cientista de Dados", "trainee"),
    ("Estágio em Ciência de Dados", "estagio"), ("Cientista de Dados Jr", "junior"),
])
def test_trainee_is_a_seniority(title, seniority):
    assert classify_role(title)[1] == seniority


def test_trainee_is_accepted_in_the_criteria():
    criteria = parse_criteria("- Cargos alvo: Cientista de Dados\n- Senioridades buscadas: Trainee, Júnior\n"
                              "- Níveis de experiência: trainee 0-1, junior 0-2, pleno 2-5\n")

    assert criteria.search_seniorities == ("trainee", "junior")
    assert [level.name for level in criteria.years_by_level][0] in ("trainee", "junior")


# --- triagem, salário e buscas com um cargo livre --------------------------------------------------

@pytest.fixture
def backend(tmp_path):
    path = tmp_path / "criterios-triagem.md"
    path.write_text("- Cargos alvo: Desenvolvedor Backend (Backend Developer)\n- Aderência mínima: 0\n"
                    "- Locais aceitos para híbrido e presencial: SP: São Paulo\n", encoding="utf-8")
    (tmp_path / "politica-salarial.md").write_text(POLICY, encoding="utf-8")
    return path


def test_a_free_role_goes_through_triage_with_its_own_key(db_path, tmp_path, backend):
    fetcher = Fetcher()
    url = fetcher.add(gupy(1, name="Desenvolvedora Backend Pleno"))
    other = fetcher.add(gupy(2, name="Cientista de Dados Pleno"))
    with connect(db_path) as conn:
        triage = Triage(conn, fetcher=fetcher, criteria_path=backend, policy_path=tmp_path / "politica-salarial.md",
                        draft_path=tmp_path / "curriculo.yaml")
        result = triage.triage_job(url)
        discarded = triage.triage_job(other)

    assert result["decision"] == "a_aplicar" and result["posting"]["role_key"] == "desenvolvedor_backend"
    assert any("Desenvolvedor Backend" in r for r in result["reasons"])
    research = next((n for n in result["needs"] if n["kind"] == "pesquisa_salarial"), None)
    assert research and any("desenvolvedor backend" in q.lower() or "Desenvolvedora Backend" in q
                            for q in research["queries"])
    assert discarded["decision"] == "descartada" and "fora dos cargos alvo" in discarded["application"]["discard_reason"]


def test_salary_queries_use_the_role_name():
    assert research_queries(None, None, None, "desenvolvedor_backend", "pleno")[-1] == \
        "salário desenvolvedor backend pleno Brasil"


def test_searches_are_built_from_the_users_roles(db_path, tmp_path, backend):
    with connect(db_path) as conn:
        result = board(conn, BoardFetcher(), backend, tmp_path).suggest_job_searches()

    queries = {s["query"] for s in result["searches"]}
    assert {"Desenvolvedor Backend", "Backend Developer"} <= queries
    assert not any("cientista" in q for q in queries)


# --- pelo MCP --------------------------------------------------------------------------------------

async def test_suggest_target_roles_reads_the_resume_and_the_criteria(db_path, backend, monkeypatch):
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(backend))
    async with Client(build_server(db_path)) as client:
        before = (await client.call_tool("suggest_target_roles", {})).structured_content
    with connect(db_path) as conn:
        store = ResumeStore(conn, default_draft_path(db_path))
        store.save_master_draft(fictitious_resume())
        store.approve_master()
    async with Client(build_server(db_path)) as client:
        after = (await client.call_tool("suggest_target_roles", {})).structured_content
        salary = await client.call_tool("find_salary_estimate", {"role_key": "desenvolvedor_backend",
                                                                 "seniority": "trainee", "currency": "BRL"})

    assert before["suggestions"] == [] and "currículo geral" in before["note"]
    assert before["current"] == [{"name": "Desenvolvedor Backend (Backend Developer)", "key": "desenvolvedor_backend",
                                  "target": True}]
    assert after["suggestions"] and "note" not in after
    assert all({"name", "key", "from"} <= set(s) for s in after["suggestions"])
    assert not salary.is_error  # cargo livre e trainee valem na pesquisa salarial
