import json
import os
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from test_job_board import card, page
from test_triage import gupy
from vagas.db import connect
from vagas.job_board import JobBoard
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore
from vagas.search_run import SearchRunStore, SearchRunner
from vagas.server import build_server
from vagas.triage import Triage

pytestmark = pytest.mark.anyio

CRITERIA = "- Cargos alvo: data_scientist\n- Empresas ignoradas: CI&T\n- Locais aceitos para híbrido e presencial: São Paulo\n"
POLICY = "- Modo: minimo\n- Remoto nacional (BRL, CLT): mínimo 8000\n- Híbrido em São Paulo (BRL, CLT): mínimo 10000\n"


def linkedin_cards(*ids):
    return "".join(
        f'<li><div data-entity-urn="urn:li:jobPosting:{i}"><h3 class="base-search-card__title">Cientista de Dados'
        f'</h3><h4 class="base-search-card__subtitle"><a>{company(i)}</a></h4>'
        f'<span class="job-search-card__location">Brasil</span></div></li>' for i in ids)


def company(job_id):
    return "Beta" if int(job_id) % 2 else "Gama"


def linkedin_job(job_id):
    return (f'<html><h1 class="top-card-layout__title topcard__title">Cientista de Dados Pleno</h1>'
            f'<a class="topcard__org-name-link" href="#">{company(job_id)}</a>'
            f'<span class="topcard__flavor--bullet">Brasil</span>'
            f'<div class="show-more-less-html__markup">Vaga 100% remota com Python e SQL.</div></html>')


class Web:
    """Um site falso para a busca e para as páginas das vagas."""

    def __init__(self, linkedin_status=200):
        self.linkedin_status = linkedin_status
        self.calls = []
        _, gupy_a = gupy(101, company="Acme", mode="hybrid", city="São Paulo")
        _, gupy_b = gupy(102, company="CI&T", mode="remote")
        self.jobs = {"https://acme.gupy.io/jobs/101": gupy_a, "https://acme.gupy.io/jobs/102": gupy_b}

    def __call__(self, url):
        self.calls.append(url)
        if "portal.gupy.io/job-search" in url:
            return 200, page([card(101, city="São Paulo", mode="hybrid"), card(102, company="CI&T")])
        if "jobs-guest" in url:
            if self.linkedin_status != 200:
                return self.linkedin_status, ""
            start = int(parse_qs(urlsplit(url).query)["start"][0])
            return 200, linkedin_cards(9001, 9002) if start == 0 else ""
        if "linkedin.com/jobs/view/" in url:
            return 200, linkedin_job(url.rstrip("/").rsplit("/", 1)[1])
        return (200, self.jobs[url]) if url in self.jobs else (404, "")


@pytest.fixture
def setup(db_path, tmp_path, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    (tmp_path / "criterios.md").write_text(CRITERIA, encoding="utf-8")
    (tmp_path / "politica.md").write_text(POLICY, encoding="utf-8")
    conn = connect(db_path)
    resumes = ResumeStore(conn, tmp_path / "curriculo.yaml")
    resumes.save_master_draft(fictitious_resume())
    resumes.approve_master()
    yield conn, tmp_path
    conn.close()


def runner(conn, tmp_path, web):
    board = JobBoard(conn, fetcher=web, criteria_path=tmp_path / "criterios.md", draft_path=tmp_path / "curriculo.yaml")
    triage = Triage(conn, fetcher=web, criteria_path=tmp_path / "criterios.md", policy_path=tmp_path / "politica.md",
                    draft_path=tmp_path / "curriculo.yaml")
    return SearchRunner(conn, board, triage, limit_wait_seconds=0)


def test_run_searches_triages_and_summarizes(setup):
    conn, tmp_path = setup
    web = Web()
    store = SearchRunStore(conn)
    run_id = store.create({"sources": ["gupy", "linkedin"], "linkedin_remote_only": True, "max_pages": 1})

    runner(conn, tmp_path, web).run(run_id)
    run = store.get(run_id)

    assert run["status"] == "done" and run["finished_at"]
    summary = run["summary"]
    # gupy: 2 línguas x (remoto + São Paulo) + 1 com a skill; linkedin: só remoto, 2 línguas
    assert summary["searches"]["run"] == 7
    assert summary["jobs"] == {"found": 4, "already_registered": 0, "triaged": 4}
    assert summary["decisions"] == {"a_aplicar": 3, "descartada": 1}
    assert {d["company"] for d in summary["descartadas"]} == {"CI&T"}
    assert all(a["id"] for a in summary["a_aplicar"])
    # Toda vaga citada no resumo tem a URL, para virar link Markdown.
    assert all(v["url"] for v in summary["a_aplicar"] + summary["descartadas"])
    assert "pesquisa_salarial" in summary["needs"]
    assert run["progress"]["searches_done"] == run["progress"]["searches_total"] == 7
    assert run["progress"]["jobs_done"] == 4
    linkedin_searches = [c for c in web.calls if "jobs-guest" in c]
    assert all("location=Brazil" in c for c in linkedin_searches)  # LinkedIn só remoto, sem cidade


def test_second_run_skips_recent_searches_and_known_jobs(setup):
    conn, tmp_path = setup
    store = SearchRunStore(conn)
    first = store.create({})
    runner(conn, tmp_path, Web()).run(first)
    second = store.create({})

    runner(conn, tmp_path, Web()).run(second)

    summary = store.get(second)["summary"]
    assert summary["searches"]["run"] == 0 and summary["searches"]["skipped"] == 7
    assert summary["jobs"]["triaged"] == 0


def test_linkedin_limit_does_not_stop_the_run(setup):
    conn, tmp_path = setup
    store = SearchRunStore(conn)
    run_id = store.create({})

    runner(conn, tmp_path, Web(linkedin_status=429)).run(run_id)

    run = store.get(run_id)
    assert run["status"] == "done"
    assert run["summary"]["decisions"] == {"a_aplicar": 1, "descartada": 1}
    assert any("limitou" in e["error"] for e in run["summary"]["errors"])


def test_only_one_run_at_a_time_and_dead_runs_are_interrupted(setup):
    conn, _ = setup
    store = SearchRunStore(conn)
    first = store.create({})
    store.set_pid(first, os.getpid())  # processo vivo

    with pytest.raises(VagasError, match="em andamento"):
        store.create({})

    store.set_pid(first, 2 ** 22 + 12345)  # PID que não existe
    second = store.create({})
    assert store.get(first)["status"] == "interrompida"
    assert store.get(second)["status"] == "running"


def test_unknown_run_and_invalid_params(setup):
    conn, _ = setup
    store = SearchRunStore(conn)
    with pytest.raises(VagasError, match="não existe"):
        store.get(999)
    with pytest.raises(VagasError, match="sources"):
        store.create({"sources": ["indeed"]})
    with pytest.raises(VagasError, match="max_pages"):
        store.create({"max_pages": 9})


async def test_start_and_get_via_mcp(db_path, setup):
    launched = []
    server = build_server(db_path, search_launcher=lambda run_id: launched.append(run_id) or os.getpid())
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        started = (await client.call_tool("start_search_run", {"sources": ["gupy"]})).structured_content
        status = (await client.call_tool("get_search_run", {})).structured_content
        again = await client.call_tool("start_search_run", {})

    assert launched == [started["run_id"]] and started["status"] == "running"
    assert status["id"] == started["run_id"] and status["params"]["sources"] == ["gupy"]
    assert again.is_error and "em andamento" in again.content[0].text
    assert "get_search_run" in tools["start_search_run"].description


async def test_real_background_process_runs_to_the_end(tmp_path, monkeypatch):
    import asyncio

    from vagas.job_search import JobSearchStore

    db = tmp_path / "dados" / "vagas.db"
    criteria = tmp_path / "criterios.md"
    criteria.write_text(CRITERIA, encoding="utf-8")
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(criteria))
    conn = connect(db)
    board = JobBoard(conn, criteria_path=criteria, draft_path=tmp_path / "c.yaml")
    for s in board.suggest_job_searches()["searches"]:  # todas recentes: o processo não acessa a rede
        JobSearchStore(conn).save_job_search(s["query"], s["source"], 0, location=s["location"])
    conn.close()

    async with Client(build_server(db)) as client:
        started = (await client.call_tool("start_search_run", {})).structured_content
        for _ in range(100):
            run = (await client.call_tool("get_search_run", {"run_id": started["run_id"]})).structured_content
            if run["status"] != "running":
                break
            await asyncio.sleep(0.1)

    assert run["status"] == "done", run
    # sem currículo aprovado não há a busca com a skill: 2 línguas x (gupy remoto + SP, linkedin remoto)
    assert run["summary"]["searches"]["skipped"] == 6 and run["summary"]["searches"]["run"] == 0
    assert (db.parent / "search_runs.log").exists()
