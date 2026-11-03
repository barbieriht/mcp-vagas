import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore
from vagas.server import build_server

pytestmark = pytest.mark.anyio

DESCRIPTION = "Requisitos: Python, XGBoost e Kafka."


@pytest.fixture
def stores(db_path, tmp_path):
    conn = connect(db_path)
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    s.save_master_draft(fictitious_resume())
    s.approve_master()
    yield s, Repo(conn)
    conn.close()


def add(repo, status="a_aplicar", description=DESCRIPTION, **extra):
    if status == "pendente_usuario":
        extra.setdefault("pending", "CPF")
    if status == "descartada":
        extra.setdefault("discard_reason", "x")
    return repo.add_application(company="Acme", role="DS", source="gupy", status=status, description=description,
                                match_score=0, match_terms={"matched": [], "missing": []}, **extra)["application"]


def test_approving_a_new_master_rescores_open_applications(stores, tmp_path):
    s, repo = stores
    open_app, pending, applied, no_text = add(repo), add(repo, "pendente_usuario"), add(repo, "aplicada"), add(
        repo, description=None)

    resume = fictitious_resume()
    resume["skills"].append({"id": "skills-ml", "label": "Machine Learning", "terms": ["XGBoost"]})
    s.save_master_draft(resume, overwrite=True)
    result = s.approve_master()

    assert result["created"] is True and result["rescored"] == 2
    assert repo.get(open_app["id"])["match_score"] == 67  # Python e XGBoost de Python, XGBoost, Kafka
    assert repo.get(open_app["id"])["match_terms"] == {"matched": ["Python", "XGBoost"], "missing": ["Kafka"]}
    assert repo.get(pending["id"])["match_score"] == 67
    assert repo.get(applied["id"])["match_score"] == 0  # candidatura já enviada não muda
    assert repo.get(no_text["id"])["match_score"] == 0


def test_same_master_does_not_rescore(stores):
    s, repo = stores
    add(repo)

    result = s.approve_master()

    assert result["created"] is False and result["rescored"] == 0


def test_rescore_on_demand_by_status(stores):
    s, repo = stores
    a, b = add(repo), add(repo, "aplicada")

    assert s.rescore_applications() == {"rescored": 1, "unchanged": 0}
    assert s.rescore_applications(status="aplicada") == {"rescored": 1, "unchanged": 0}
    assert s.rescore_applications() == {"rescored": 0, "unchanged": 1}
    with pytest.raises(VagasError, match="status"):
        s.rescore_applications(status="inexistente")


def test_repo_rejects_invalid_scores(stores):
    _, repo = stores
    app = add(repo)
    with pytest.raises(VagasError, match="match_score"):
        repo.set_match(app["id"], 120, {"matched": [], "missing": []})


async def test_rescore_tool_via_mcp(db_path, tmp_path):
    async with Client(build_server(db_path, draft_path=tmp_path / "curriculo.yaml")) as client:
        await client.call_tool("save_master_draft", {"resume": fictitious_resume()})
        await client.call_tool("approve_master", {})
        await client.call_tool("add_application", {"company": "Acme", "role": "DS", "source": "gupy",
                                                   "status": "a_aplicar", "description": DESCRIPTION})
        tools = {t.name: t for t in (await client.list_tools()).tools}
        result = (await client.call_tool("rescore_applications", {})).structured_content

    assert result == {"rescored": 1, "unchanged": 0}
    assert "rescored" in tools["approve_master"].description
