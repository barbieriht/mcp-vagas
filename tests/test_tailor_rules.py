"""Regras de redação do currículo personalizado: resumo curto e sem disponibilidade, parágrafos em ordem."""

import itertools

import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore
from vagas.resume_suggest import suggest_selection
from vagas.resume_tailor import SUMMARY_MAX, TailoredSelection, resolve

LONG = ("Data scientist building ETL pipelines in Python and SQL. " * 12).strip()
P1, P2, P3 = "exp-acme-tech-lead-p1", "exp-acme-tech-lead-p2", "exp-acme-tech-lead-p3"


def master(summary=None):
    resume = fictitious_resume()
    resume["experience"][0]["paragraphs"].append(
        {"id": P3, "text": "Additionally, mentored analysts on SQL and Python best practices."})
    if summary:
        resume["summary"] = summary
    return resume


@pytest.fixture
def make_store(db_path, tmp_path):
    ticks = itertools.count()
    conn = connect(db_path)

    def make(resume):
        store = ResumeStore(conn, tmp_path / "curriculo.yaml", now=lambda: f"2026-10-27T12:00:{next(ticks):02d}+00:00")
        store.save_master_draft(resume, overwrite=True)
        store.approve_master()
        return store
    yield make
    conn.close()


def tech_lead(*ids):
    return {"section": "experience", "items": [{"id": "exp-acme-tech-lead", "paragraphs": [{"id": i} for i in ids]}]}


def test_paragraphs_keep_the_master_order():
    resolved = resolve(master(), TailoredSelection.model_validate({"sections": [tech_lead(P2, P1)]}))

    assert [p["id"] for p in resolved["experience"][0]["paragraphs"]] == [P1, P2]


def test_a_paragraph_that_continues_another_needs_an_earlier_one_or_bullets():
    with pytest.raises(VagasError, match=f"{P3}.*Additionally"):
        resolve(master(), TailoredSelection.model_validate({"sections": [tech_lead(P3)]}))

    resolve(master(), TailoredSelection.model_validate({"sections": [tech_lead(P2, P3)]}))
    rewritten = {"section": "experience", "items": [{"id": "exp-acme-tech-lead", "paragraphs": [
        {"id": P3, "bullets": ["Mentored analysts on SQL and Python best practices."]}]}]}
    resolve(master(), TailoredSelection.model_validate({"sections": [rewritten]}))


def test_long_master_summary_must_be_replaced_by_one_for_the_job(make_store, tmp_path):
    store = make_store(master(summary=LONG))
    out = tmp_path / "Curriculos"

    with pytest.raises(VagasError, match=f"summary.*{SUMMARY_MAX}"):
        store.create_tailored_resume({"label": "X", "sections": [tech_lead(P1)]}, out)

    created = store.create_tailored_resume(
        {"label": "X", "summary": "Data scientist building ETL pipelines in Python and SQL.",
         "sections": [tech_lead(P1)]}, out)
    assert created["pages"] >= 1


@pytest.mark.parametrize("summary", [
    "Data scientist in Python and SQL. Currently open to Data Scientist opportunities (remote or São Carlos).",
    "Data scientist in Python and SQL, seeking remote roles.",
    "Data scientist in Python and SQL. Available for hybrid positions.",
    "Data scientist. Areas of expertise: Python; SQL.",
])
def test_summary_without_availability_or_skill_lists(make_store, tmp_path, summary):
    store = make_store(master())

    with pytest.raises(VagasError, match="summary"):
        store.create_tailored_resume({"label": "X", "summary": summary, "sections": [tech_lead(P1)]},
                                     tmp_path / "Curriculos")


def test_suggestion_keeps_master_order_and_brings_the_paragraph_a_continuation_needs():
    selection = suggest_selection(master(), ["Mentored", "SQL"], label="X")["selection"]

    paragraphs = selection["sections"][1]["items"][0]["paragraphs"] if selection["sections"][0]["section"] != \
        "experience" else selection["sections"][0]["items"][0]["paragraphs"]
    ids = [p["id"] for p in paragraphs]
    assert ids == sorted(ids) and P3 in ids and ids[0] != P3
    resolve(master(), TailoredSelection.model_validate(selection))
