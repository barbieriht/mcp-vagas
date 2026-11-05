import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore
from vagas.resume_suggest import suggest_selection
from vagas.resume_tailor import TailoredSelection, resolve
from vagas.server import build_server

pytestmark = pytest.mark.anyio


def master():
    resume = fictitious_resume()
    resume["experience"][0]["paragraphs"].append(
        {"id": "exp-acme-tech-lead-p3", "text": "Mentored analysts on SQL and Python best practices."})
    resume["skills"].append({"id": "skills-cloud", "label": "Cloud", "terms": ["Terraform", "AWS", "Kubernetes"]})
    resume["volunteering"] = [
        {"id": "vol-ong", "organization": "ONG", "role": "Mentor",
         "paragraphs": [{"id": "vol-ong-p1", "text": "Taught Python to teenagers."}]},
        {"id": "vol-clube", "organization": "Clube", "role": "Tesoureiro",
         "paragraphs": [{"id": "vol-clube-p1", "text": "Managed the budget."}]},
    ]
    return resume


def picks(selection, section):
    return next((s for s in selection["sections"] if s["section"] == section), None)


def test_paragraphs_and_skills_follow_the_job_terms():
    m = master()
    result = suggest_selection(m, ["Qdrant", "LangChain", "AWS", "Python", "Kubernetes"], label="Beta")

    selection = result["selection"]
    experience = picks(selection, "experience")["items"]
    assert [i["id"] for i in experience] == ["exp-acme-tech-lead", "exp-acme-analyst"]  # ordem do currículo
    assert [p["id"] for p in experience[0]["paragraphs"]] == [
        "exp-acme-tech-lead-p1", "exp-acme-tech-lead-p2", "exp-acme-tech-lead-p3"]
    assert result["scores"]["paragraphs"] == {
        "exp-acme-tech-lead-p1": 2, "exp-acme-tech-lead-p2": 2, "exp-acme-tech-lead-p3": 1,
        "exp-acme-analyst-p1": 1, "vol-ong-p1": 1, "vol-clube-p1": 0}
    skills = picks(selection, "skills")["items"]
    assert [g["id"] for g in skills] == ["skills-cloud", "skills-languages"]
    assert skills[0]["terms"] == ["AWS", "Kubernetes", "Terraform"]
    assert skills[1]["terms"][0] == "Python"
    assert [i["id"] for i in picks(selection, "volunteering")["items"]] == ["vol-ong"]
    assert picks(selection, "education")["items"] is None and picks(selection, "languages")["items"] is None
    assert selection["label"] == "Beta"


def test_low_scoring_paragraphs_are_dropped_but_every_job_keeps_one():
    m = master()
    result = suggest_selection(m, ["LangChain"], label=None)

    experience = picks(result["selection"], "experience")["items"]
    assert [p["id"] for p in experience[0]["paragraphs"]] == ["exp-acme-tech-lead-p1"]
    assert [p["id"] for p in experience[1]["paragraphs"]] == ["exp-acme-analyst-p1"]  # nenhum casou: fica o 1º
    assert picks(result["selection"], "volunteering") is None
    assert picks(result["selection"], "certifications") is None


def test_suggestion_is_accepted_by_the_resume_validation():
    m = master()
    selection = suggest_selection(m, ["Qdrant", "Python", "GraphRAG"], label="X")["selection"]

    resolved = resolve(m, TailoredSelection.model_validate(selection))
    assert resolved["certifications"][0]["items"][0]["id"] == "cert-genai-graphrag"


def test_without_terms_everything_comes_in_master_order():
    result = suggest_selection(master(), [], label=None)

    assert all(s["items"] is None for s in result["selection"]["sections"])
    assert "termos" in result["note"]


@pytest.fixture
def store(db_path, tmp_path):
    conn = connect(db_path)
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    s.save_master_draft(master())
    s.approve_master()
    yield s, Repo(conn)
    conn.close()


def test_store_uses_the_application_terms_or_its_description(store):
    s, repo = store
    with_terms = repo.add_application(company="Beta", role="AI Engineer", source="gupy", status="a_aplicar",
                                      match_score=50, match_terms={"matched": ["LangChain"], "missing": []})
    with_text = repo.add_application(company="Gama", role="DS", source="gupy", status="a_aplicar",
                                     description="Vaga com Kubernetes e Terraform.")

    a = s.suggest_tailored_selection(with_terms["application"]["id"])
    b = s.suggest_tailored_selection(with_text["application"]["id"])

    assert a["terms"] == ["LangChain"] and a["selection"]["label"] == "Beta - AI Engineer"
    assert b["terms"] == ["Kubernetes", "Terraform"]
    with pytest.raises(VagasError, match="não existe"):
        s.suggest_tailored_selection(999)


async def test_suggest_then_create_via_mcp(db_path, tmp_path):
    server = build_server(db_path, draft_path=tmp_path / "curriculo.yaml", resume_out=tmp_path / "pdfs")
    async with Client(server) as client:
        await client.call_tool("save_master_draft", {"resume": master()})
        await client.call_tool("approve_master", {})
        app = (await client.call_tool("add_application", {
            "company": "Beta", "role": "AI Engineer", "source": "gupy", "status": "a_aplicar",
            "match_terms": {"matched": ["Qdrant", "Python"], "missing": []}})).structured_content["application"]
        tools = {t.name: t for t in (await client.list_tools()).tools}
        suggestion = (await client.call_tool("suggest_tailored_selection",
                                             {"application_id": app["id"]})).structured_content
        created = await client.call_tool("create_tailored_resume", {"selection": suggestion["selection"],
                                                                    "application_id": app["id"]})

    assert not created.is_error, created.content
    assert "create_tailored_resume" in tools["suggest_tailored_selection"].description


def test_certifications_are_capped_by_relevance():
    m = master()
    m["certifications"][0]["items"] = [
        {"id": f"cert-{n}", "name": f"Course {n} on Python" + (" and Qdrant" if n % 2 else ""),
         "provider": "Exemplo"} for n in range(10)]

    result = suggest_selection(m, ["Python", "Qdrant"], label=None)

    certs = picks(result["selection"], "certifications")["items"][0]["items"]
    assert certs == ["cert-1", "cert-3", "cert-5", "cert-7", "cert-9", "cert-0"]
