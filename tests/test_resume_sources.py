import itertools
import sqlite3

import pytest

from resume_fixture import fictitious_resume
from vagas.db import MIGRATIONS, connect
from vagas.repo import VagasError
from vagas.resume_render import render_resume
from vagas.resume_repo import ResumeStore

PROFILE = "https://www.linkedin.com/in/fulana/"
LINKEDIN = {
    "about": "Data scientist working with LLM applications.",
    "certifications": "Kubernetes for Developers\nThe Linux Foundation\nIssued Mar 2025\n"
                      "GraphRAG Essential Training\nLinkedIn Learning\nIssued 2026",
}


@pytest.fixture
def store(db_path, tmp_path):
    ticks = itertools.count()
    conn = connect(db_path)
    yield ResumeStore(conn, tmp_path / "curriculo.yaml", now=lambda: f"2026-10-27T12:00:{next(ticks):02d}+00:00")
    conn.close()


@pytest.fixture
def pdf(tmp_path):
    return render_resume(fictitious_resume(), tmp_path / "pdf")["path"]


def with_linkedin_only_cert():
    resume = fictitious_resume()
    resume["certifications"][0]["items"].append(
        {"id": "cert-genai-k8s", "name": "Kubernetes for Developers", "provider": "The Linux Foundation", "year": 2025})
    return resume


def review_pairs(result):
    return {(item["where"], item["value"]) for item in result["review"]}


def test_saves_linkedin_source_with_section_sizes(store):
    result = store.save_resume_source("linkedin", PROFILE, LINKEDIN)

    assert result["source_id"] > 0
    assert result["sections"] == {name: len(text) for name, text in LINKEDIN.items()}


@pytest.mark.parametrize("sections, message", [
    ({}, "sections"),
    ({"skills": "Python"}, "skills"),
    ({"about": "   "}, "about"),
])
def test_invalid_sections_are_rejected(store, sections, message):
    with pytest.raises(VagasError, match=message):
        store.save_resume_source("linkedin", PROFILE, sections)


def test_invalid_kind_and_blank_url_are_rejected(store):
    with pytest.raises(VagasError, match="kind"):
        store.save_resume_source("twitter", PROFILE, LINKEDIN)
    with pytest.raises(VagasError, match="url"):
        store.save_resume_source("linkedin", "  ", LINKEDIN)


def test_review_uses_pdf_and_linkedin_together(store, pdf):
    store.extract_resume_text(pdf)
    store.save_resume_source("linkedin", PROFILE, LINKEDIN)

    result = store.save_master_draft(with_linkedin_only_cert())

    assert result["review"] == []
    assert result["sources"] == [{"kind": "pdf", "path": pdf}, {"kind": "linkedin", "path": PROFILE}]


def test_item_only_in_linkedin_is_flagged_without_linkedin_source(store, pdf):
    store.extract_resume_text(pdf)

    result = store.save_master_draft(with_linkedin_only_cert())

    assert ("cert-genai-k8s.name", "Kubernetes for Developers") in review_pairs(result)


def test_item_in_no_source_is_flagged(store, pdf):
    store.extract_resume_text(pdf)
    store.save_resume_source("linkedin", PROFILE, LINKEDIN)
    resume = with_linkedin_only_cert()
    resume["certifications"][0]["items"].append({"id": "cert-genai-x", "name": "Invented Course"})

    assert review_pairs(store.save_master_draft(resume)) == {("cert-genai-x.name", "Invented Course")}


def test_linkedin_alone_is_a_valid_reference(store):
    store.save_resume_source("linkedin", PROFILE, LINKEDIN)

    result = store.save_master_draft(fictitious_resume())

    assert result["sources"] == [{"kind": "linkedin", "path": PROFILE}]
    assert ("exp-acme-analyst.company", "Acme Analytics") in review_pairs(result)


def test_latest_source_of_each_kind_is_used(store):
    store.save_resume_source("linkedin", PROFILE, {"about": "Old text."})
    store.save_resume_source("linkedin", PROFILE, LINKEDIN)
    resume = {"basics": {"name": "Fulana"}, "summary": "Working with LLM applications.",
              "certifications": [{"id": "cert-x", "label": "Certs", "items": [
                  {"id": "cert-x-k8s", "name": "Kubernetes for Developers"}]}]}

    review = store.save_master_draft(resume)["review"]

    assert {item["where"] for item in review} == {"basics.name", "cert-x.label"}


def test_without_sources_there_is_no_review(store):
    result = store.save_master_draft(fictitious_resume())

    assert (result["sources"], result["review"]) == ([], None)


def test_migration_keeps_existing_pdf_sources(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    steps = [s for s in MIGRATIONS if isinstance(s, str)]
    v4 = MIGRATIONS.index(next(s for s in MIGRATIONS if isinstance(s, str) and "resume_sources" in s)) + 1
    for step in MIGRATIONS[:v4]:
        old.executescript(step)
    old.execute("INSERT INTO resume_sources (path, pages, extracted_at) VALUES ('/x/cv.pdf', '[\"Acme\"]', 't')")
    old.execute(f"PRAGMA user_version = {v4}")
    old.commit()
    old.close()
    assert steps

    conn = connect(path)
    store = ResumeStore(conn, tmp_path / "c.yaml")
    result = store.save_master_draft({"basics": {"name": "Acme"}})

    assert result["sources"] == [{"kind": "pdf", "path": "/x/cv.pdf"}]
    assert result["review"] == []
