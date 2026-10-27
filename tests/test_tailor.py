import itertools

import pypdf
import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore

P1 = "exp-acme-tech-lead-p1"  # "... reducing answer latency by 30% for 2M monthly requests."
P2 = "exp-acme-tech-lead-p2"  # "Ran the platform on AWS (S3, Lambda) and Kubernetes/K3s with Terraform."


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "Curriculos"


@pytest.fixture
def store(db_path, tmp_path):
    ticks = itertools.count()
    conn = connect(db_path)
    s = ResumeStore(conn, tmp_path / "curriculo.yaml", now=lambda: f"2026-10-27T12:00:{next(ticks):02d}+00:00")
    s.save_master_draft(fictitious_resume())
    s.approve_master()
    yield s
    conn.close()


def tech_lead(*paragraphs):
    return {"section": "experience", "items": [{"id": "exp-acme-tech-lead", "paragraphs": list(paragraphs)}]}


def selection(*sections, **extra):
    return {"label": "Nubank", "sections": list(sections), **extra}


def pdf_text(path):
    return " ".join(" ".join(page.extract_text() for page in pypdf.PdfReader(path).pages).split())


def test_creates_validates_renders_and_registers(store, out_dir):
    result = store.create_tailored_resume(selection(tech_lead({"id": P1})), out_dir)

    assert result["id"] > 0
    assert result["path"] == str(out_dir / "Fulana_Tal_Resume_Nubank.pdf")
    assert result["pages"] == 1
    assert result["warnings"] == []


def test_legitimate_rewrite_is_accepted_and_rendered_as_bullets(store, out_dir):
    bullets = [
        "Led a conversational assistant using FastAPI, LangChain and Qdrant",
        "Cut answer latency by 30% across 2M monthly requests",
    ]

    result = store.create_tailored_resume(selection(tech_lead({"id": P1, "bullets": bullets})), out_dir)

    text = pdf_text(result["path"])
    assert all(bullet in text for bullet in bullets)
    assert "Coordinated a conversational assistant" not in text


def test_terms_with_symbols_and_acronyms_from_master_are_accepted(store, out_dir):
    chosen = selection(
        tech_lead({"id": P2, "bullets": ["Operated AWS S3, Lambda and K3s clusters with Terraform"]}),
        headline="Data Scientist | C++ and C# developer",
        summary="Data scientist building ETL pipelines in Python and SQL with LangChain.",
    )

    result = store.create_tailored_resume(chosen, out_dir)

    text = pdf_text(result["path"])
    assert "Data Scientist | C++ and C# developer" in text
    assert "Operated AWS S3, Lambda and K3s clusters with Terraform" in text


@pytest.mark.parametrize(
    "chosen, expected",
    [
        (selection(tech_lead({"id": P1, "bullets": ["Cut latency by 45% for 2M requests"]})), [P1, "45%"]),
        (selection(tech_lead({"id": P1, "bullets": ["Served 20M monthly requests"]})), [P1, "20M"]),
        (selection(tech_lead({"id": P1}), headline="Data Scientist with 3+ years"), ["headline", "3+"]),
        (selection(tech_lead({"id": P1}), summary="Engineer with 5 years in data."), ["summary", "5"]),
        (selection(tech_lead({"id": P2, "bullets": ["Deployed services with Docker on AWS"]})), [P2, "Docker"]),
        (selection(tech_lead({"id": P1}), summary="Expert in Kubernetes and Rust."), ["summary", "Rust"]),
        (selection({"section": "experience", "items": [{"id": "exp-nope"}]}), ["exp-nope"]),
        (selection({"section": "experience", "items": [
            {"id": "exp-acme-analyst", "paragraphs": [{"id": P1}]}]}), [P1, "exp-acme-analyst"]),
        (selection({"section": "experience", "items": [
            {"id": "exp-acme-analyst", "title": "Head of Data"}]}), ["title"]),
        (selection({"section": "education", "items": [
            {"id": "edu-uni-phd", "degree": "M.Sc."}]}), ["degree"]),
        (selection({"section": "skills", "items": [
            {"id": "skills-languages", "terms": ["Python", "Rust"]}]}), ["skills-languages", "Rust"]),
        (selection({"section": "certifications", "items": [
            {"id": "cert-genai", "items": ["cert-other"]}]}), ["cert-genai", "cert-other"]),
        (selection(tech_lead({"id": P1}), tech_lead({"id": P2})), ["experience"]),
        (selection({"section": "skills", "items": [
            {"id": "skills-languages", "paragraphs": [{"id": P1}]}]}), ["skills-languages", "paragraphs"]),
    ],
    ids=[
        "invented-number", "inflated-number", "years-claim", "summary-number", "invented-tech",
        "invented-tech-summary", "unknown-id", "paragraph-of-other-item", "factual-field-title",
        "factual-field-degree", "skill-not-in-group", "cert-not-in-group", "duplicate-section",
        "paragraphs-on-skills",
    ],
)
def test_invented_or_inconsistent_content_is_rejected(store, out_dir, chosen, expected):
    with pytest.raises(VagasError) as error:
        store.create_tailored_resume(chosen, out_dir)

    message = str(error.value)
    assert all(fragment in message for fragment in expected), message
    assert not out_dir.exists() or list(out_dir.iterdir()) == []
    assert store.list_resumes() == []


def test_all_problems_are_reported_at_once(store, out_dir):
    chosen = selection(tech_lead({"id": P1, "bullets": ["Cut latency by 45%", "Used Docker"]}))

    with pytest.raises(VagasError) as error:
        store.create_tailored_resume(chosen, out_dir)

    assert "45%" in str(error.value) and "Docker" in str(error.value)


def test_pdf_has_only_selected_items_in_requested_order(store, out_dir):
    chosen = selection(
        {"section": "skills"},
        {"section": "experience", "items": [
            {"id": "exp-acme-analyst"},
            {"id": "exp-acme-tech-lead", "paragraphs": [{"id": P2}]},
        ]},
    )

    text = pdf_text(store.create_tailored_resume(chosen, out_dir)["path"])

    assert text.index("Technical Skills") < text.index("Experience")
    assert text.index("Quantitative Analyst") < text.index("AI Engineering Technical Coordinator")
    assert "Ran the platform on AWS" in text
    assert "Coordinated a conversational assistant" not in text
    assert "Universidade Exemplo" not in text
    assert "Certifications" not in text


def test_skill_and_certification_subsets_keep_requested_order(store, out_dir):
    chosen = selection(
        {"section": "skills", "items": [{"id": "skills-languages", "terms": ["SQL", "python"]}]},
    )

    text = pdf_text(store.create_tailored_resume(chosen, out_dir)["path"])

    assert "Programming Languages: SQL, Python" in text
    assert "C++" not in text


def test_factual_fields_always_come_from_master(store, out_dir):
    result = store.create_tailored_resume(selection(tech_lead({"id": P2})), out_dir)

    job = store.get_resume(result["id"])["resolved"]["experience"][0]
    assert (job["company"], job["title"], job["start"], job["end"]) == (
        "Acme Analytics", "AI Engineering Technical Coordinator", "May 2024", "Sep 2025",
    )


def test_registry_keeps_selection_resolved_content_and_master_version(store, out_dir):
    chosen = selection(tech_lead({"id": P1, "bullets": ["Cut answer latency by 30%"]}))

    created = store.create_tailored_resume(chosen, out_dir)
    saved = store.get_resume(created["id"])

    assert saved["master_resume_id"] == store.get_master_resume()["version_id"]
    assert saved["selection"]["sections"][0]["items"][0]["paragraphs"][0]["bullets"] == ["Cut answer latency by 30%"]
    assert saved["resolved"]["experience"][0]["paragraphs"] == [{"id": P1, "bullets": ["Cut answer latency by 30%"]}]
    assert (saved["pdf_path"], saved["pages"], saved["label"]) == (created["path"], 1, "Nubank")
    assert store.list_resumes() == [{
        "id": created["id"], "label": "Nubank", "pdf_path": created["path"], "pages": 1,
        "master_resume_id": saved["master_resume_id"], "application_id": None,
        "created_at": saved["created_at"],
    }]


def test_unknown_resume_is_a_readable_error(store):
    with pytest.raises(VagasError, match="999"):
        store.get_resume(999)


def test_requires_an_approved_master(db_path, tmp_path, out_dir):
    conn = connect(db_path)
    empty = ResumeStore(conn, tmp_path / "outro.yaml")

    with pytest.raises(VagasError, match="approve_master"):
        empty.create_tailored_resume(selection(tech_lead({"id": P1})), out_dir)
