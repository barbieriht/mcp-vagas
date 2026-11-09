"""Anotações sobre as fontes ("PDF lists...", "LinkedIn: ...") não entram no currículo: nem no geral, nem no personalizado."""

import itertools
import json

import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore
from vagas.resume_validate import source_notes

NOTE = "PDF lists a certification; LinkedIn: Professional working proficiency"


@pytest.mark.parametrize("text", [
    NOTE, "Per LinkedIn, promoted to lead", "According to the PDF, the course ended in 2020", "only on LinkedIn",
    "Segundo o LinkedIn, inglês fluente", "Fonte: PDF", "LinkedIn shows 2021", "the PDF mentions Spark",
    "Not in the PDF", "consta no PDF",
])
def test_source_notes_are_detected(text):
    assert source_notes(text)


@pytest.mark.parametrize("text", [
    "LinkedIn Learning", "Built a PDF parser that extracts tables from reports", "https://www.linkedin.com/in/fulano/",
    "Certification (CEPE Idiomas)", "Upper-intermediate (B2)", "Generated PDF reports for regulators",
    "Automated LinkedIn outreach campaigns",
])
def test_resume_text_is_left_alone(text):
    assert source_notes(text) == []


@pytest.fixture
def store(db_path, tmp_path):
    ticks = itertools.count()
    conn = connect(db_path)
    yield ResumeStore(conn, tmp_path / "curriculo.yaml", now=lambda: f"2026-10-27T12:00:{next(ticks):02d}+00:00")
    conn.close()


def with_note(note=NOTE):
    resume = fictitious_resume()
    resume["languages"][0]["note"] = note
    return resume


def test_draft_with_a_source_note_is_rejected_naming_the_field(store, tmp_path):
    with pytest.raises(VagasError) as error:
        store.save_master_draft(with_note())

    message = str(error.value)
    assert "languages/English/note" in message and "PDF lists a certification" in message
    assert "conversa" in message
    assert not (tmp_path / "curriculo.yaml").exists()


def test_hand_edited_draft_with_a_source_note_is_not_approved(store, tmp_path):
    store.save_master_draft(fictitious_resume())
    draft = tmp_path / "curriculo.yaml"
    draft.write_text(draft.read_text(encoding="utf-8").replace("note: Certification", f"note: '{NOTE}'"),
                     encoding="utf-8")

    with pytest.raises(VagasError, match="languages/English/note"):
        store.approve_master()


def test_tailored_resume_rejects_source_notes_in_rewrites_and_in_an_old_master(store, tmp_path):
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    out = tmp_path / "Curriculos"

    with pytest.raises(VagasError, match="headline.*Per LinkedIn"):
        store.create_tailored_resume({"label": "X", "headline": "Per LinkedIn, Tech Lead",
                                      "sections": [{"section": "languages"}]}, out)

    # versão aprovada antes desta regra, com a anotação gravada
    row = store.conn.execute("SELECT id, content FROM master_resumes ORDER BY id DESC LIMIT 1").fetchone()
    content = json.loads(row["content"])
    content["languages"][0]["note"] = NOTE
    with store.conn:
        store.conn.execute("UPDATE master_resumes SET content = ? WHERE id = ?", (json.dumps(content), row["id"]))

    with pytest.raises(VagasError) as error:
        store.create_tailored_resume({"label": "X", "sections": [{"section": "languages"}]}, out)

    assert "currículo geral" in str(error.value) and "languages/English/note" in str(error.value)
    assert not out.exists() or list(out.iterdir()) == []
