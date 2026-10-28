import copy

import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_extract import review_draft
from vagas.resume_render import render_resume
from vagas.resume_repo import ResumeStore

ALURA = {
    "id": "cert-genai-langchain",
    "name": "LangChain: Orchestrating Generative AI Applications",
    "name_original": "LangChain: orquestrando aplicações de IA generativa",
    "provider": "Alura",
    "issued": "2025-06",
    "credential_id": "ALURA-123",
    "description": "Course covering LangGraph agents and MLflow tracking.",
}


def with_cert(**changes):
    resume = fictitious_resume()
    resume["certifications"][0]["items"].append({**copy.deepcopy(ALURA), **changes})
    return resume


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


def store_for(conn, tmp_path, resume):
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    s.save_master_draft(resume)
    s.approve_master()
    return s


def test_new_certification_fields_are_kept(conn, tmp_path):
    master = store_for(conn, tmp_path, with_cert()).get_master_resume()["resume"]

    assert master["certifications"][0]["items"][1] == ALURA


def test_old_drafts_without_new_fields_remain_valid(conn, tmp_path):
    assert store_for(conn, tmp_path, fictitious_resume()).get_master_resume()["version_id"]


@pytest.mark.parametrize("issued", ["2025-6", "06/2025", "2025-13"])
def test_issued_must_be_year_or_year_month(conn, tmp_path, issued):
    with pytest.raises(VagasError, match="issued"):
        ResumeStore(conn, tmp_path / "x.yaml").save_master_draft(with_cert(issued=issued))


def test_issued_and_year_must_agree(conn, tmp_path):
    with pytest.raises(VagasError, match="issued"):
        ResumeStore(conn, tmp_path / "x.yaml").save_master_draft(with_cert(year=2024))
    assert ResumeStore(conn, tmp_path / "y.yaml").save_master_draft(with_cert(year=2025))["path"]


def test_duplicate_credential_id_is_rejected_with_guidance(conn, tmp_path):
    resume = with_cert()
    resume["certifications"][0]["items"].append({**ALURA, "id": "cert-genai-langchain-2", "issued": "2025-09"})

    with pytest.raises(VagasError, match="ALURA-123.*mais antiga"):
        ResumeStore(conn, tmp_path / "x.yaml").save_master_draft(resume)


def test_review_accepts_original_title():
    reference = "LangChain: orquestrando aplicações de IA generativa Alura Issued Jun 2025 Credential ID ALURA-123"
    draft = {"basics": {"name": "Alura"}, "certifications": [
        {"id": "cert-x", "label": "Alura", "items": [{**ALURA, "description": None}]}]}

    review = review_draft(draft, reference)

    assert review == []


def test_review_flags_when_neither_title_is_in_sources():
    draft = {"basics": {"name": "Alura"}, "certifications": [
        {"id": "cert-x", "label": "Alura", "items": [{**ALURA, "description": None}]}]}

    review = {(i["where"], i["value"]) for i in review_draft(draft, "Alura 2025 ALURA-123")}

    assert ("cert-genai-langchain.name", ALURA["name"]) in review


def test_description_terms_do_not_validate_experience_bullets(conn, tmp_path):
    store = store_for(conn, tmp_path, with_cert())
    selection = {"sections": [{"section": "experience", "items": [{"id": "exp-acme-analyst", "paragraphs": [
        {"id": "exp-acme-analyst-p1", "bullets": ["Maintained ETL pipelines in Python with MLflow"]}]}]}]}

    with pytest.raises(VagasError, match="MLflow"):
        store.create_tailored_resume(selection, tmp_path / "out")


def test_certification_names_still_count_for_validation(conn, tmp_path):
    store = store_for(conn, tmp_path, with_cert())
    selection = {"summary": "Data scientist trained in LangChain.", "sections": [{"section": "skills"}]}

    assert store.create_tailored_resume(selection, tmp_path / "out")["path"]


def test_pdf_shows_year_from_issued(tmp_path):
    import pypdf

    path = render_resume(with_cert(), tmp_path / "out")["path"]
    text = " ".join(" ".join(p.extract_text() for p in pypdf.PdfReader(path).pages).split())

    assert "LangChain: Orchestrating Generative AI Applications – Alura (2025)" in text
    assert "orquestrando" not in text and "LangGraph" not in text
