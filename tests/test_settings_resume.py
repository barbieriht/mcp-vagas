"""Currículo geral no painel: ler o rascunho (ou a versão aprovada) e gravar o rascunho editado."""

import copy

import pytest
import yaml

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.resume_repo import ResumeStore, default_draft_path
from vagas.settings_form import load, save


@pytest.fixture
def store(db_path):
    conn = connect(db_path)
    yield ResumeStore(conn, default_draft_path(db_path))
    conn.close()


def section(db_path):
    return load(db_path)["sections"]["resume"]


def test_without_any_resume_the_section_says_how_to_start(db_path):
    data = section(db_path)

    assert "monte meu currículo geral" in data["error"].lower()


def test_approved_resume_is_shown_when_there_is_no_draft(db_path, store):
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    default_draft_path(db_path).unlink()

    data = section(db_path)

    assert data["origin"] == "approved" and data["value"]["basics"]["name"] == "Fulana de Tal"
    labels = {f["key"]: f for f in data["schema"]["fields"]}
    assert labels["experience"]["type"] == "list"
    assert {f["key"] for f in labels["experience"]["item"]["fields"]} >= {"company", "title", "start", "end",
                                                                         "paragraphs"}


def test_draft_is_shown_with_a_fingerprint(db_path, store):
    store.save_master_draft(fictitious_resume())

    data = section(db_path)

    assert data["origin"] == "draft" and data["hash"] and data["file"] == str(default_draft_path(db_path))


def edited(db_path):
    data = section(db_path)
    return copy.deepcopy(data["value"]), data["hash"]


def test_saving_writes_the_draft_keeps_ids_and_creates_the_new_ones(db_path, store):
    resume = fictitious_resume()
    resume["experience"][0]["title_aliases"] = ["Tech Lead"]  # campo que o painel não mostra
    store.save_master_draft(resume)
    value, fingerprint = edited(db_path)
    value["experience"][0]["title"] = "AI Engineering Coordinator"
    value["experience"][0]["paragraphs"].append({"text": "Mentored two junior engineers."})
    value["experience"].insert(0, {"company": "Nova Empresa", "title": "Data Scientist", "start": "Oct 2025",
                                   "end": "", "location": "", "paragraphs": [{"text": "Built churn models."}]})

    result = save({"resume": {"data": value, "hash": fingerprint}}, db_path)

    assert result["saved"], result["errors"]
    draft = yaml.safe_load(default_draft_path(db_path).read_text(encoding="utf-8"))
    new, old = draft["experience"][0], draft["experience"][1]
    assert new["id"] == "exp-nova-empresa-data-scientist" and new["paragraphs"][0]["id"] == f"{new['id']}-p1"
    assert "location" not in new and "end" not in new  # campos vazios saem
    assert old["id"] == "exp-acme-tech-lead" and old["title"] == "AI Engineering Coordinator"
    assert old["title_aliases"] == ["Tech Lead"]
    assert [p["id"] for p in old["paragraphs"]] == ["exp-acme-tech-lead-p1", "exp-acme-tech-lead-p2",
                                                    "exp-acme-tech-lead-p3"]


def test_invalid_fields_point_to_the_field_and_nothing_is_written(db_path, store):
    store.save_master_draft(fictitious_resume())
    before = default_draft_path(db_path).read_text(encoding="utf-8")
    value, fingerprint = edited(db_path)
    value["experience"][1]["company"] = ""
    value["experience"][1]["paragraphs"] = []

    result = save({"resume": {"data": value, "hash": fingerprint}}, db_path)

    assert not result["saved"]
    assert set(result["errors"]) == {"resume.experience.1.company", "resume.experience.1.paragraphs"}
    assert result["errors"]["resume.experience.1.company"] == "Campo obrigatório."
    assert default_draft_path(db_path).read_text(encoding="utf-8") == before


def test_a_draft_changed_after_opening_the_panel_is_not_overwritten(db_path, store):
    store.save_master_draft(fictitious_resume())
    value, fingerprint = edited(db_path)
    changed = fictitious_resume()
    changed["basics"]["headline"] = "Escrito pelo Claude enquanto o painel estava aberto"
    store.save_master_draft(changed, overwrite=True)

    result = save({"resume": {"data": value, "hash": fingerprint}}, db_path)

    assert not result["saved"] and "recarregue" in result["errors"]["resume"].lower()
    assert "Escrito pelo Claude" in default_draft_path(db_path).read_text(encoding="utf-8")


def test_notes_about_the_sources_are_refused_like_in_the_chat(db_path, store):
    store.save_master_draft(fictitious_resume())
    value, fingerprint = edited(db_path)
    value["languages"] = [{"name": "English", "level": "B2", "note": "PDF lists B2, LinkedIn says C1"}]

    result = save({"resume": {"data": value, "hash": fingerprint}}, db_path)

    assert not result["saved"] and "fontes" in result["errors"]["resume"]
