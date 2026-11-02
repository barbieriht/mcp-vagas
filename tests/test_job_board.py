import json
from urllib.parse import unquote

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.job_board import JobBoard, gupy_search_url, parse_gupy_search
from vagas.job_search import JobSearchStore
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore
from vagas.server import build_server

pytestmark = pytest.mark.anyio

CRITERIA = """\
- Cargos alvo: data_scientist, ml_engineer
- Locais aceitos para híbrido e presencial: São Carlos, São Paulo
"""


def card(job_id, name="Cientista de Dados", company="Acme", mode="remote", city="", state="", disabilities=False):
    return {"id": job_id, "name": name, "careerPageName": company, "type": "vacancy_type_effective",
            "workplaceType": mode, "city": city, "state": state, "publishedDate": "2026-10-30T12:00:00.000Z",
            "description": "texto longo", "disabilities": disabilities,
            "jobUrl": f"https://acme.gupy.io/jobs/{job_id}?jobBoardSource=gupy_portal"}


def page(cards, total=None, offset=0, limit=12):
    data = {"props": {"pageProps": {"initialJobList": {
        "data": cards, "pagination": {"total": len(cards) if total is None else total, "limit": limit,
                                      "offset": offset}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


class Fetcher:
    """Serve páginas por número (parâmetro page) e guarda as URLs pedidas."""

    def __init__(self, pages=None, status=200):
        self.pages, self.status, self.calls = pages or {}, status, []

    def __call__(self, url):
        self.calls.append(unquote(url))
        number = int(url.split("&page=")[1].split("&")[0]) if "&page=" in url else 1
        return self.status, self.pages.get(number, page([]))


def test_search_page_is_parsed_into_results():
    jobs, pagination = parse_gupy_search(page([
        card(1, city="São Paulo", state="São Paulo", mode="hybrid", disabilities=True),
        card(2, name="Data Scientist", company="Beta", mode="on-site", city="São Carlos", state="São Paulo"),
    ], total=30))

    assert pagination == {"total": 30, "limit": 12, "offset": 0}
    assert jobs[0] == {"title": "Cientista de Dados", "company": "Acme", "url": "https://acme.gupy.io/jobs/1",
                       "published_at": "2026-10-30", "location": "São Paulo, São Paulo", "work_mode": "hibrido",
                       "contract": "clt", "pcd_flag": True}
    assert (jobs[1]["work_mode"], jobs[1]["location"]) == ("presencial", "São Carlos, São Paulo")


def test_page_without_search_data_is_a_clear_error():
    with pytest.raises(VagasError, match="formato"):
        parse_gupy_search("<html>nada</html>")


def test_search_url_has_term_location_filters_and_page():
    url = unquote(gupy_search_url("cientista de dados", "São Paulo",
                                  {"work_modes": ["hibrido", "presencial"], "state": "São Paulo"}, page=2))

    assert url.startswith("https://portal.gupy.io/job-search/term=cientista de dados")
    assert "&city=São Paulo" in url and "&state=São Paulo" in url
    assert "&workplaceTypes[]=hybrid&workplaceTypes[]=on-site" in url and url.endswith("&page=2")


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def criteria(tmp_path):
    path = tmp_path / "criterios-triagem.md"
    path.write_text(CRITERIA, encoding="utf-8")
    return path


def board(conn, fetcher, criteria, tmp_path):
    return JobBoard(conn, fetcher=fetcher, criteria_path=criteria, draft_path=tmp_path / "curriculo.yaml")


def test_search_reads_pages_registers_and_marks_known_jobs(conn, criteria, tmp_path):
    fetcher = Fetcher({1: page([card(i) for i in range(1, 13)], total=15),
                       2: page([card(i) for i in range(13, 16)], total=15, offset=12)})
    Repo(conn).add_application(company="Acme", role="DS", source="gupy", url="https://acme.gupy.io/jobs/3",
                               status="aplicada")

    result = board(conn, fetcher, criteria, tmp_path).search_jobs("cientista de dados", "gupy")

    assert (result["skipped"], result["total"], result["pages_read"], len(result["results"])) == (False, 15, 2, 15)
    assert result["results"][2]["registered"] == {"id": 1, "status": "aplicada"}
    assert result["results"][0]["registered"] is None
    saved = JobSearchStore(conn).find_job_search("cientista de dados", "gupy")["search"]
    assert (saved["id"], saved["results_count"]) == (result["search_id"], 15)


def test_max_pages_limits_the_reading(conn, criteria, tmp_path):
    fetcher = Fetcher({n: page([card(n * 100 + i) for i in range(12)], total=60, offset=(n - 1) * 12)
                       for n in range(1, 6)})

    result = board(conn, fetcher, criteria, tmp_path).search_jobs("x", "gupy", filters={"max_pages": 3})

    assert (result["pages_read"], len(result["results"]), len(fetcher.calls)) == (3, 36, 3)
    assert JobSearchStore(conn).find_job_search("x", "gupy")["search"]["filters"] == {"max_pages": 3}


def test_recent_search_is_skipped_unless_forced(conn, criteria, tmp_path):
    fetcher = Fetcher({1: page([card(1)])})
    jobs = board(conn, fetcher, criteria, tmp_path)
    jobs.search_jobs("cientista de dados", "gupy", location="São Paulo")

    again = jobs.search_jobs("Cientista de Dados", "gupy", location="sao paulo")
    forced = jobs.search_jobs("cientista de dados", "gupy", location="São Paulo", force=True)

    assert again["skipped"] is True and again["results"] == [] and again["previous"]["results_count"] == 1
    assert forced["skipped"] is False and len(fetcher.calls) == 2


@pytest.mark.parametrize("source, filters, message", [
    ("indeed", None, "navegador"),
    ("gupy", {"cor": "azul"}, "cor"),
    ("gupy", {"work_modes": ["teletrabalho"]}, "work_modes"),
    ("gupy", {"max_pages": 9}, "max_pages"),
])
def test_invalid_search_is_a_clear_error(conn, criteria, tmp_path, source, filters, message):
    with pytest.raises(VagasError, match=message):
        board(conn, Fetcher(), criteria, tmp_path).search_jobs("x", source, filters=filters)


def test_blocked_search_is_a_clear_error_and_not_registered(conn, criteria, tmp_path):
    with pytest.raises(VagasError, match="navegador"):
        board(conn, Fetcher(status=403), criteria, tmp_path).search_jobs("x", "gupy")
    assert JobSearchStore(conn).find_job_search("x", "gupy")["search"] is None


def approve(conn, tmp_path):
    store = ResumeStore(conn, tmp_path / "curriculo.yaml")
    store.save_master_draft(fictitious_resume())
    store.approve_master()


def test_suggestions_combine_roles_skills_and_locations(conn, criteria, tmp_path):
    approve(conn, tmp_path)
    jobs = board(conn, Fetcher(), criteria, tmp_path)

    result = jobs.suggest_job_searches()

    combos = {(s["query"], s["location"], tuple(s["filters"].get("work_modes", []))) for s in result["searches"]}
    assert ("cientista de dados", None, ("remoto",)) in combos
    assert ("data scientist", None, ("remoto",)) in combos
    assert ("machine learning engineer", "São Carlos", ("hibrido", "presencial")) in combos
    assert ("cientista de dados", "São Paulo", ("hibrido", "presencial")) in combos
    assert result["skills"] and set(result["skills"]) <= {"Python", "SQL", "C++", "C#"}
    assert (f"data scientist {result['skills'][0].lower()}", None, ("remoto",)) in combos
    assert all(s["source"] == "gupy" and s["recent"] is False for s in result["searches"])


def test_seniorities_from_criteria_become_query_variants(conn, tmp_path):
    path = tmp_path / "c.md"
    path.write_text("- Cargos alvo: data_scientist\n- Senioridades buscadas: pleno, senior\n", encoding="utf-8")

    result = board(conn, Fetcher(), path, tmp_path).suggest_job_searches()

    queries = {s["query"] for s in result["searches"]}
    assert {"cientista de dados pleno", "cientista de dados sênior", "data scientist pleno"} <= queries
    assert "cientista de dados" not in queries


def test_suggestions_flag_recent_searches_and_work_without_resume(conn, criteria, tmp_path):
    JobSearchStore(conn).save_job_search("cientista de dados", "gupy", 4, filters={"work_modes": ["remoto"]})

    result = board(conn, Fetcher(), criteria, tmp_path).suggest_job_searches()

    recent = [s for s in result["searches"] if s["recent"]]
    assert [(s["query"], s["location"]) for s in recent] == [("cientista de dados", None)]
    assert result["skills"] == [] and "currículo" in result["note"]


async def test_search_and_suggest_via_mcp(db_path, criteria, tmp_path, monkeypatch):
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(criteria))
    fetcher = Fetcher({1: page([card(1)])})
    server = build_server(db_path, draft_path=tmp_path / "curriculo.yaml", job_search_fetcher=fetcher)
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        found = (await client.call_tool("search_jobs", {
            "query": "cientista de dados", "source": "gupy", "filters": {"work_modes": ["remoto"]}})).structured_content
        suggested = (await client.call_tool("suggest_job_searches", {})).structured_content
        bad = await client.call_tool("search_jobs", {"query": "x", "source": "glassdoor"})

    assert found["results"][0]["url"] == "https://acme.gupy.io/jobs/1" and found["search_id"] > 0
    assert suggested["searches"] and "triage_job" in tools["search_jobs"].description
    assert "find_job_search" in tools["search_jobs"].description
    assert bad.is_error and "navegador" in bad.content[0].text
