import json

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import Repo
from vagas.resume_repo import ResumeStore
from vagas.server import build_server
from vagas.work_list import build_work_list

pytestmark = pytest.mark.anyio


@pytest.fixture
def stores(db_path, tmp_path):
    conn = connect(db_path)
    resumes = ResumeStore(conn, tmp_path / "curriculo.yaml")
    resume = fictitious_resume()
    resume["skills"].append({"id": "skills-ml", "label": "ML", "terms": ["LightGBM"]})
    resumes.save_master_draft(resume)
    resumes.approve_master()
    yield conn, Repo(conn), resumes
    conn.close()


def add(repo, conn, company, score, work_mode="remoto", seniority="pleno", evaluation=None, **extra):
    app = repo.add_application(company=company, role="Cientista de Dados", source="gupy", status="a_aplicar",
                               url=f"https://{company.lower()}.gupy.io/jobs/1", work_mode=work_mode,
                               seniority=seniority, location="São Paulo, SP", match_score=score,
                               match_terms={"matched": ["Python"], "missing": ["XGBoost", "Kafka", "Spark"]},
                               **extra)["application"]
    if evaluation:
        conn.execute("UPDATE applications SET salary_evaluation = ? WHERE id = ?", (json.dumps(evaluation), app["id"]))
        conn.commit()
    return app


def test_rows_are_split_into_ready_and_pending(stores):
    conn, repo, resumes = stores
    add(repo, conn, "Alfa", 90, evaluation={"decision": "aplicar", "value_to_inform": 12000, "basis": "mercado"})
    add(repo, conn, "Beta", 80, work_mode=None, evaluation={"decision": "aplicar", "value_to_inform": 9000})
    add(repo, conn, "Gama", 70, evaluation={"decision": "pesquisar", "value_to_inform": None})
    add(repo, conn, "Delta", 60, seniority=None)
    repo.add_application(company="Zeta", role="DS", source="gupy", status="aplicada")

    result = build_work_list(repo, resumes)

    assert [r["company"] for r in result["ready"]] == ["Alfa"]
    assert [(r["company"], r["pending"]) for r in result["pending"]] == [
        ("Beta", ["modalidade"]), ("Gama", ["pesquisa salarial"]), ("Delta", ["senioridade", "salário não avaliado"])]
    alfa = result["ready"][0]
    assert alfa["value_to_inform"] == 12000 and alfa["salary_basis"] == "mercado"
    assert alfa["missing"] == ["XGBoost", "Kafka", "Spark"]
    assert alfa["related"] == {"XGBoost": ["LightGBM"]}
    assert alfa["url"] == "https://alfa.gupy.io/jobs/1" and alfa["work_mode"] == "remoto"
    assert result["counts"] == {"ready": 1, "pending": 3}


def test_registered_pending_text_is_a_pendency(stores):
    conn, repo, resumes = stores
    app = add(repo, conn, "Alfa", 90, evaluation={"decision": "aplicar", "value_to_inform": 12000})
    repo.update_application(app["id"], pending="responder pergunta sobre disponibilidade")

    result = build_work_list(repo, resumes)

    assert result["pending"][0]["pending"] == ["responder pergunta sobre disponibilidade"]


def test_works_without_approved_resume(db_path, tmp_path):
    conn = connect(db_path)
    repo = Repo(conn)
    add(repo, conn, "Alfa", 90, evaluation={"decision": "aplicar", "value_to_inform": 12000})

    result = build_work_list(repo, ResumeStore(conn, tmp_path / "c.yaml"))
    conn.close()

    assert result["ready"][0]["related"] == {}


async def test_work_list_via_mcp(db_path, tmp_path):
    async with Client(build_server(db_path, draft_path=tmp_path / "c.yaml")) as client:
        await client.call_tool("add_application", {"company": "Alfa", "role": "DS", "source": "gupy",
                                                   "status": "a_aplicar", "work_mode": "remoto", "seniority": "pleno"})
        tools = {t.name: t for t in (await client.list_tools()).tools}
        result = (await client.call_tool("work_list", {})).structured_content

    assert result["counts"] == {"ready": 0, "pending": 1}
    assert "pending" in tools["work_list"].description


def test_rows_show_the_contract(stores):
    conn, repo, resumes = stores
    add(repo, conn, "Alfa", 90, contract="pj", evaluation={"decision": "aplicar", "value_to_inform": 12000})
    add(repo, conn, "Beta", 80, evaluation={"decision": "aplicar", "value_to_inform": 9000})
    add(repo, conn, "Gama", 70, work_mode=None, contract="clt")

    result = build_work_list(repo, resumes)

    assert [(r["company"], r["contract"]) for r in result["ready"]] == [("Alfa", "pj"), ("Beta", "desconhecido")]
    assert result["pending"][0]["contract"] == "clt"
