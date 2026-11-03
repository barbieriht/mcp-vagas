import json

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.job_search import JobSearchStore
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore
from vagas.salary import SalaryStore
from vagas.server import build_server
from vagas.triage import Triage

CRITERIA = """\
- Cargos alvo: data_scientist, ml_engineer
- Cargos condicionados à aderência: data_engineer
- Aderência mínima: 50
- Empresas ignoradas: CI&T
- Termos de vaga exclusiva PcD: exclusiva para PcD
- Locais aceitos para híbrido e presencial: São Paulo
"""
POLICY = """\
- Modo: minimo
- Multiplicador PJ: 1.4
- Remoto nacional (BRL, CLT): mínimo 8.000
- Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10.000
"""
GOOD = "<p>Modelos com Python e SQL.</p>"
BAD = "<p>Kafka, Airflow, Hadoop, Scala, Spark, Flink, Kubernetes.</p>"


def gupy(job_id, name="Cientista de Dados Pleno", company="Acme", mode="hybrid", city="São Paulo",
         job_type="vacancy_type_effective", description=GOOD):
    job = {"id": job_id, "name": name, "jobType": job_type, "workplaceType": mode, "addressCity": city,
           "addressState": "SP", "addressCountry": "Brasil", "handicapped": False, "description": description,
           "careerPage": {"name": company}}
    page = ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"job": job}}}) + "</script></html>")
    return f"https://acme.gupy.io/jobs/{job_id}", page


def linkedin(job_id, salary=None, remote=False):
    obj = {"@type": "JobPosting", "title": "Senior Data Scientist", "hiringOrganization": {"name": "Beta"},
           "jobLocation": {"address": {"addressLocality": "São Paulo", "addressCountry": "BR"}},
           "description": GOOD}
    if remote:
        obj["jobLocationType"] = "TELECOMMUTE"
    if salary:
        obj["baseSalary"] = salary
    page = f'<html><script type="application/ld+json">{json.dumps(obj)}</script></html>'
    return f"https://www.linkedin.com/jobs/view/{job_id}/", page


class Fetcher:
    def __init__(self):
        self.pages, self.calls = {}, []

    def add(self, url_page):
        url, page = url_page
        self.pages[url] = page
        return url

    def __call__(self, url):
        self.calls.append(url)
        return (200, self.pages[url]) if url in self.pages else (403, "Just a moment")


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def files(tmp_path):
    (tmp_path / "criterios-triagem.md").write_text(CRITERIA, encoding="utf-8")
    (tmp_path / "politica-salarial.md").write_text(POLICY, encoding="utf-8")
    return tmp_path


@pytest.fixture
def approved(conn, files):
    store = ResumeStore(conn, files / "curriculo.yaml")
    store.save_master_draft(fictitious_resume())
    store.approve_master()


@pytest.fixture
def fetcher():
    return Fetcher()


@pytest.fixture
def triage(conn, files, fetcher, approved, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    return Triage(conn, fetcher=fetcher, criteria_path=files / "criterios-triagem.md",
                  policy_path=files / "politica-salarial.md", draft_path=files / "curriculo.yaml")


def market(conn, value, seniority="pleno", role_key="data_scientist"):
    SalaryStore(conn).save_salary_estimate(role_key, seniority, "BRL", points=[
        {"source": "glassdoor", "period": "mes", "contract": "clt", "avg_value": value}])


def kinds(result):
    return [need["kind"] for need in result["needs"]]


def test_target_job_is_registered_scored_and_salary_evaluated(triage, fetcher, conn):
    url = fetcher.add(gupy(1))
    market(conn, 12000)

    result = triage.triage_job(url)

    app = result["application"]
    assert result["decision"] == "a_aplicar"
    assert (app["status"], app["role"], app["company"], app["work_mode"], app["location"], app["source"]) == (
        "a_aplicar", "Cientista de Dados Pleno", "Acme", "hibrido", "São Paulo, SP, Brasil", "gupy")
    assert app["match_score"] == 100 and app["match_terms"]["matched"] == ["Python", "SQL"]
    assert "Modelos com Python" in app["description"]
    assert (result["salary"]["decision"], result["salary"]["value_to_inform"]) == ("aplicar", 12000)
    assert result["salary"]["policy"]["band"] == "Híbrido/presencial em São Paulo e região"
    assert app["salary_evaluation"]["value_to_inform"] == 12000
    assert kinds(result) == ["pesquisa_salarial"]  # mercado fresco, empresa ainda não pesquisada
    assert "description" not in result["posting"]
    assert any("data_scientist" in r for r in result["reasons"])


def test_already_registered_url_is_not_read_again(triage, fetcher, conn):
    url = fetcher.add(gupy(2))
    Repo(conn).add_application(company="Acme", role="DS", source="gupy", url=url + "?utm_source=x",
                               status="aplicada")
    fetcher.calls.clear()

    result = triage.triage_job(url)

    assert result["decision"] == "ja_registrada"
    assert result["application"]["status"] == "aplicada"
    assert fetcher.calls == []


@pytest.mark.parametrize("page, reason", [
    (gupy(3, company="CI&T"), "CI&T"),
    (gupy(4, name="Cientista de Dados - Exclusiva para PcD"), "PcD"),
    (gupy(5, name="Engenheiro de Dados Pleno", description=BAD), "aderência"),
    (gupy(6, name="Data Scientist Pleno", mode="remote", job_type="vacancy_type_legal_entity"), "Mediana"),
])
def test_rejected_jobs_are_registered_as_discarded(triage, fetcher, conn, page, reason):
    url = fetcher.add(page)
    market(conn, 7000)  # PJ: 7.000 x 1.4 abaixo de 8.000 x 1.4

    result = triage.triage_job(url)

    assert result["decision"] == "descartada"
    assert result["application"]["status"] == "descartada"
    assert reason in result["application"]["discard_reason"]


def test_conditional_role_with_good_match_goes_on(triage, fetcher):
    url = fetcher.add(gupy(7, name="Engenheiro de Dados Pleno"))

    result = triage.triage_job(url)

    assert result["decision"] == "a_aplicar"
    assert any("aderência" in r for r in result["reasons"])


def test_published_range_is_saved_and_has_priority(triage, fetcher, conn):
    salary = {"currency": "BRL", "value": {"minValue": 5000, "maxValue": 7000, "unitText": "MONTH"}}
    url = fetcher.add(linkedin(8, salary=salary, remote=True))

    result = triage.triage_job(url)

    assert result["decision"] == "descartada"
    assert result["salary"]["basis"] == "vaga"
    assert "faixa publicada" in result["application"]["discard_reason"].lower()


def test_uncertain_role_location_and_missing_data_become_needs(triage, fetcher):
    role = triage.triage_job(fetcher.add(gupy(9, name="Software Engineer")))
    place = triage.triage_job(fetcher.add(gupy(10, city="Recife")))
    no_mode = triage.triage_job(fetcher.add(linkedin(11)))
    no_level = triage.triage_job(fetcher.add(gupy(12, name="Cientista de Dados", mode="remote")))

    assert role["decision"] == "a_aplicar" and kinds(role)[0] == "cargo"
    assert place["decision"] == "a_aplicar" and "local" in kinds(place)
    assert "Recife" in next(n["detail"] for n in place["needs"] if n["kind"] == "local")
    assert no_mode["decision"] == "a_aplicar" and "modalidade" in kinds(no_mode)
    assert no_level["decision"] == "a_aplicar" and "senioridade" in kinds(no_level)
    assert role["salary"] is None and no_mode["salary"] is None and no_level["salary"] is None


def test_no_salary_data_asks_for_research(triage, fetcher):
    result = triage.triage_job(fetcher.add(gupy(13, mode="remote")))

    assert result["salary"]["decision"] == "pesquisar"
    assert result["decision"] == "a_aplicar" and "pesquisa_salarial" in kinds(result)


def test_possible_duplicate_on_another_platform_is_not_registered(triage, fetcher, conn):
    Repo(conn).add_application(company="Acme Ltda", role="Cientista de Dados Pleno", source="linkedin",
                               location="São Paulo, SP", url="https://www.linkedin.com/jobs/view/99/",
                               status="a_aplicar")
    url = fetcher.add(gupy(14))

    first = triage.triage_job(url)
    confirmed = triage.triage_job(url, not_duplicate=True)

    assert first["decision"] == "possivel_duplicata" and first["application"] is None
    assert kinds(first) == ["possivel_duplicata"]
    assert first["needs"][0]["matches"][0]["url"] == "https://www.linkedin.com/jobs/view/99/"
    assert confirmed["decision"] == "a_aplicar"


def test_search_id_is_recorded(triage, fetcher, conn):
    search_id = JobSearchStore(conn).save_job_search("cientista de dados", "gupy", 3)["search_id"]

    result = triage.triage_job(fetcher.add(gupy(15)), search_id=search_id)

    assert result["application"]["search_id"] == search_id


def test_blocked_page_tells_to_read_in_the_browser(triage):
    with pytest.raises(VagasError, match="navegador"):
        triage.triage_job("https://br.indeed.com/viewjob?jk=abc")


def test_without_approved_resume_match_becomes_a_need(conn, files, fetcher):
    triage = Triage(conn, fetcher=fetcher, criteria_path=files / "criterios-triagem.md",
                    policy_path=files / "politica-salarial.md", draft_path=files / "curriculo.yaml")

    result = triage.triage_job(fetcher.add(gupy(16)))

    assert result["decision"] == "a_aplicar" and "aderencia" in kinds(result)


async def test_triage_job_via_mcp(db_path, files, fetcher, monkeypatch):
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(files / "criterios-triagem.md"))
    monkeypatch.setenv("VAGAS_SALARY_POLICY", str(files / "politica-salarial.md"))
    url = fetcher.add(gupy(17, mode="remote"))
    server = build_server(db_path, draft_path=files / "curriculo.yaml", job_fetcher=fetcher)
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        result = (await client.call_tool("triage_job", {"url": url})).structured_content
        blocked = await client.call_tool("triage_job", {"url": "https://www.glassdoor.com.br/job-listing/x"})

    assert result["decision"] == "a_aplicar" and result["application"]["status"] == "a_aplicar"
    assert "needs" in tools["triage_job"].description and "not_duplicate" in tools["triage_job"].input_schema[
        "properties"]
    assert blocked.is_error and "navegador" in blocked.content[0].text


pytestmark = pytest.mark.anyio


def test_inferred_work_mode_is_used_and_flagged(triage, fetcher):
    page = ('<html><h1 class="top-card-layout__title topcard__title">Cientista de Dados Pleno</h1>'
            '<a class="topcard__org-name-link" href="#">Gama</a>'
            '<span class="topcard__flavor--bullet">São Paulo, SP</span>'
            '<div class="show-more-less-html__markup">Python e SQL. Modelo híbrido.</div></html>')
    url = "https://www.linkedin.com/jobs/view/12345/"
    fetcher.pages[url] = page

    result = triage.triage_job(url)

    assert result["application"]["work_mode"] == "hibrido"
    assert any("inferida" in r for r in result["reasons"]) and "modalidade" not in kinds(result)


def test_salary_research_need_brings_job_and_company_queries(triage, fetcher):
    result = triage.triage_job(fetcher.add(gupy(30, company="Zeta", mode="remote")))

    need = next(n for n in result["needs"] if n["kind"] == "pesquisa_salarial")
    assert need["queries"][0] == 'salário "Cientista de Dados Pleno" Zeta São Paulo'
    assert need["queries"][-1] == "salário cientista de dados pleno Brasil"


@pytest.mark.parametrize("registered, new, duplicate", [
    # mesma vaga em outra plataforma: título equivalente, mesma cidade
    (("Data Scientist Pleno", "São Paulo, SP"), ("Cientista de Dados Pleno", "São Paulo"), False),
    (("Cientista de Dados Pleno", "São Paulo, SP"), ("Cientista de Dados Pleno", "São Paulo"), True),
    (("Cientista de Dados Pleno - Remoto", "Brasil"), ("Cientista de Dados Pleno", "São Paulo"), True),
    # mesmo título, cidades diferentes
    (("Cientista de Dados Pleno", "Belo Horizonte, MG"), ("Cientista de Dados Pleno", "São Paulo"), False),
    # títulos diferentes na mesma empresa
    (("Cientista de Dados Pleno - Crédito", "São Paulo"), ("Cientista de Dados Pleno - Marketing", "São Paulo"),
     True),  # o sufixo depois de " - " não conta: confirmar com o usuário
    (("Cientista de Dados Pleno de Crédito e Risco", "São Paulo"), ("Cientista de Dados Pleno", "São Paulo"), False),
    # códigos de vaga diferentes
    (("Cientista de Dados Pleno | REF#100", "Brasil"), ("Cientista de Dados Pleno | REF#200", "São Paulo"), False),
])
def test_possible_duplicate_needs_equivalent_title_and_compatible_place(triage, fetcher, conn, registered, new,
                                                                        duplicate):
    role, place = registered
    Repo(conn).add_application(company="Acme", role=role, location=place, source="linkedin",
                               url="https://www.linkedin.com/jobs/view/99/", status="a_aplicar")
    title, city = new

    result = triage.triage_job(fetcher.add(gupy(40, name=title, city=city)))

    assert (result["decision"] == "possivel_duplicata") is duplicate


def test_seniority_comes_from_the_years_asked(triage, fetcher, conn):
    market(conn, 12000, seniority="pleno")
    url = fetcher.add(gupy(50, name="Cientista de Dados", mode="remote",
                           description="<p>Python e SQL. Requisitos: 4+ years of experience.</p>"))

    result = triage.triage_job(url)

    assert result["application"]["seniority"] == "pleno"
    assert "senioridade" not in kinds(result)
    assert any("4 anos" in r for r in result["reasons"])
    assert result["salary"]["decision"] == "aplicar"


def test_hybrid_outside_accepted_states_is_discarded(conn, files, fetcher, approved, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    (files / "criterios-triagem.md").write_text(
        CRITERIA + "- Estados aceitos para híbrido e presencial: SP\n", encoding="utf-8")
    triage = Triage(conn, fetcher=fetcher, criteria_path=files / "criterios-triagem.md",
                    policy_path=files / "politica-salarial.md", draft_path=files / "curriculo.yaml")
    out_url, out_page = gupy(51, city="Florianópolis")
    outside = fetcher.add((out_url, out_page.replace('"addressState": "SP"', '"addressState": "Santa Catarina"')))
    page_url, page = gupy(52, city="Campinas")
    inside = fetcher.add((page_url, page.replace('"addressState": "SP"', '"addressState": "São Paulo"')))

    far = triage.triage_job(outside)
    near = triage.triage_job(inside)

    assert far["decision"] == "descartada" and "SC" in far["application"]["discard_reason"]
    assert near["decision"] == "a_aplicar" and "local" in kinds(near)


def test_accepted_city_is_matched_against_the_city_not_the_state(triage, fetcher):
    page_url, page = gupy(53, city="Campinas")
    result = triage.triage_job(fetcher.add((page_url, page.replace('"addressState": "SP"',
                                                                   '"addressState": "São Paulo"'))))

    assert "local" in kinds(result)  # Campinas não está entre os locais aceitos (só São Paulo)
