import copy

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_diff import diff_master
from vagas.resume_model import MasterResume
from vagas.resume_repo import ResumeStore
from vagas.server import build_server

pytestmark = pytest.mark.anyio


def master():
    resume = fictitious_resume()
    resume["volunteering"] = [{"id": "vol-ong", "organization": "ONG Exemplo", "role": "Mentor", "paragraphs": []}]
    resume["certifications"][0]["items"][0]["credential_id"] = "ABC123"
    return resume


def experience(**fields):
    item = {"id": "exp-x", "company": "Acme Analytics", "title": "Quantitative Analyst", "start": "Feb 2024",
            "end": "Sep 2025", "paragraphs": [{"id": "exp-x-p1", "text": "Maintained ETL pipelines in Python and SQL."}]}
    item.update(fields)
    return item


def test_identical_items_produce_no_differences():
    m = master()
    items = {k: copy.deepcopy(m[k]) for k in ("experience", "education", "certifications", "volunteering",
                                               "languages", "skills")}

    result = diff_master(m, items)

    assert (result["new"], result["changed"], result["missing"]) == ({}, [], {})
    assert result["draft"] == m


def test_matching_tolerates_spelling_and_title_aliases():
    m = master()
    m["experience"][0]["title_aliases"] = ["Coordenador Técnico de Engenharia de IA"]
    items = {"experience": [
        experience(id="exp-qualquer", company="ACME analytics ltda.", title="Quantitative  Analyst", start="02/2024"),
        experience(id="exp-outro", title="Coordenador Técnico de Engenharia de IA", start="May 2024", end="Sep 2025",
                   paragraphs=copy.deepcopy(m["experience"][0]["paragraphs"]),
                   context="Funded AI Research Project", location="Remote"),
    ]}

    result = diff_master(m, items)

    assert result["new"] == {}
    assert result["missing"] == {}  # ambas casaram, apesar das grafias


def test_changed_fields_keep_the_existing_id():
    m = master()
    items = {"experience": [
        experience(end="Present", paragraphs=[{"id": "p", "text": "Maintained ETL pipelines in Python, SQL and dbt."}]),
        copy.deepcopy(m["experience"][0]),
    ]}

    result = diff_master(m, items)

    assert result["changed"] == [{
        "section": "experience", "id": "exp-acme-analyst",
        "fields": {"end": {"old": "Sep 2025", "new": "Present"},
                   "paragraphs": {"old": ["Maintained ETL pipelines in Python and SQL."],
                                  "new": ["Maintained ETL pipelines in Python, SQL and dbt."]}},
    }]
    assert result["draft"]["experience"][1]["end"] == "Sep 2025"  # alterações não são aplicadas sozinhas


def test_new_items_are_added_to_the_draft_with_unique_ids():
    m = master()
    items = {
        "experience": [experience(id="exp-acme-analyst", company="Beta", title="Data Scientist", start="Jan 2026",
                                  end=None, paragraphs=[{"id": "exp-acme-analyst-p1", "text": "Built models."}])],
        "certifications": [{"id": "cert-novos", "label": "Generative AI & LLMs", "items": [
            {"id": "cert-genai-graphrag", "name": "RAG Fundamentals", "provider": "Coursera", "issued": "2026-03"}]}],
        "skills": [{"id": "skills-ml", "label": "Machine Learning", "terms": ["XGBoost", "Python", "LightGBM"]},
                   {"id": "skills-x", "label": "programming languages", "terms": ["Rust", "sql"]}],
        "languages": [{"name": "Spanish", "level": "Basic (A2)"}],
        "volunteering": [{"id": "vol-novo", "organization": "Outra ONG", "role": "Voluntário"}],
    }

    result = diff_master(m, items)

    new_exp = result["new"]["experience"][0]
    assert new_exp["id"] == "exp-acme-analyst-2" and new_exp["paragraphs"][0]["id"] == "exp-acme-analyst-2-p1"
    assert [c["id"] for c in result["new"]["certifications"]] == ["cert-genai-graphrag-2"]
    assert result["new"]["skills"] == {"Machine Learning": ["XGBoost", "LightGBM"], "Programming Languages": ["Rust"]}
    assert result["new"]["languages"] == [{"name": "Spanish", "level": "Basic (A2)"}]
    assert result["new"]["volunteering"][0]["organization"] == "Outra ONG"

    draft = result["draft"]
    MasterResume.model_validate(draft)  # rascunho válido, IDs únicos
    assert draft["experience"][-1]["company"] == "Beta"
    assert [c["name"] for c in draft["certifications"][0]["items"]] == ["GraphRAG Essential Training",
                                                                        "RAG Fundamentals"]
    assert draft["skills"][0]["terms"] == ["Python", "SQL", "C++", "C#", "Rust"]
    assert draft["skills"][1] == {"id": "skills-ml", "label": "Machine Learning", "terms": ["XGBoost", "LightGBM"]}


def test_missing_items_are_reported_never_removed():
    m = master()
    items = {"experience": [copy.deepcopy(m["experience"][0])], "volunteering": []}

    result = diff_master(m, items)

    assert result["missing"] == {"experience": ["exp-acme-analyst"], "volunteering": ["vol-ong"]}
    assert len(result["draft"]["experience"]) == 2 and result["draft"]["volunteering"]
    # seções que não vieram nos itens não contam como ausentes
    assert "certifications" not in result["missing"] and "education" not in result["missing"]


def test_certifications_match_by_credential_id_first():
    m = master()
    items = {"certifications": [{"id": "g", "label": "Outro grupo", "items": [
        {"id": "c", "name": "GraphRAG (versão nova)", "provider": "LinkedIn Learning", "credential_id": "ABC123",
         "issued": "2026-01"}]}]}

    result = diff_master(m, items)

    assert result["new"] == {}
    assert result["changed"][0]["id"] == "cert-genai-graphrag"
    assert set(result["changed"][0]["fields"]) == {"name", "issued"}


def test_headline_and_summary_changes():
    m = master()
    items = {"headline": "Senior Data Scientist", "summary": m.get("summary")}

    result = diff_master(m, items)

    assert result["changed"] == [{"section": "basics", "id": "headline", "fields": {
        "headline": {"old": m["basics"]["headline"], "new": "Senior Data Scientist"}}}]


@pytest.fixture
def store(db_path, tmp_path):
    conn = connect(db_path)
    yield ResumeStore(conn, tmp_path / "curriculo.yaml")
    conn.close()


def test_store_diffs_against_the_approved_master(store):
    with pytest.raises(VagasError, match="approve_master"):
        store.diff_master({"experience": []})
    store.save_master_draft(master())
    store.approve_master()

    result = store.diff_master({"languages": [{"name": "Spanish", "level": "Basic"}]})

    assert result["new"]["languages"] == [{"name": "Spanish", "level": "Basic"}]
    assert store.get_master_resume()["resume"].get("languages")[-1]["name"] == "Portuguese"  # nada salvo


async def test_diff_master_via_mcp(db_path, tmp_path):
    server = build_server(db_path, draft_path=tmp_path / "curriculo.yaml")
    async with Client(server) as client:
        await client.call_tool("save_master_draft", {"resume": master()})
        await client.call_tool("approve_master", {})
        tools = {t.name: t for t in (await client.list_tools()).tools}
        result = (await client.call_tool("diff_master", {"items": {
            "skills": [{"id": "s", "label": "Machine Learning", "terms": ["XGBoost"]}]}})).structured_content

    assert result["new"]["skills"] == {"Machine Learning": ["XGBoost"]}
    assert "save_master_draft" in tools["diff_master"].description
    assert "import_linkedin_profile" in tools["diff_master"].description
