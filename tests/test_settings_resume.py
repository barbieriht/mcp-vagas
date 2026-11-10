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


# --- diferenças e aprovação ------------------------------------------------------------------------

from vagas.settings_resume import approve, draft_changes  # noqa: E402


def approved_then_draft(store, db_path, edit):
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    changed = fictitious_resume()
    edit(changed)
    store.save_master_draft(changed, overwrite=True)


def test_changes_list_what_the_draft_adds_removes_and_edits(db_path, store):
    def edit(resume):
        resume["experience"][0]["title"] = "AI Engineering Coordinator"
        resume["experience"].append({"id": "exp-nova", "company": "Nova", "title": "Data Scientist",
                                     "start": "Oct 2025", "paragraphs": [{"id": "exp-nova-p1", "text": "Built models."}]})
        del resume["education"][0]
        resume["basics"]["headline"] = "Data Scientist"

    approved_then_draft(store, db_path, edit)
    changes = {(c["section"], c["kind"], c.get("id")): c for c in draft_changes(store)}

    assert changes[("experience", "changed", "exp-acme-tech-lead")]["fields"] == ["title"]
    assert ("experience", "added", "exp-nova") in changes and ("education", "removed", "edu-uni-phd") in changes
    assert changes[("basics", "changed", None)]["fields"] == ["headline"]
    assert len(changes) == 4


def test_section_shows_changes_review_and_whether_it_can_be_approved(db_path, store):
    store.save_resume_source("pdf", "Curriculo.pdf", text="Fulana de Tal. Acme Analytics.")
    approved_then_draft(store, db_path, lambda r: r["basics"].update(headline="Data Scientist"))

    data = section(db_path)

    assert data["approval"]["can_approve"] and data["approval"]["changes"]
    assert any("Data Scientist" in item.get("value", "") or item.get("where") for item in data["approval"]["review"])


def test_draft_equal_to_the_approved_version_cannot_be_approved_again(db_path, store):
    store.save_master_draft(fictitious_resume())
    store.approve_master()

    approval = section(db_path)["approval"]

    assert not approval["can_approve"] and "nenhuma diferença" in approval["reason"].lower()


def test_approving_creates_the_version_and_the_draft_has_no_more_changes(db_path, store):
    approved_then_draft(store, db_path, lambda r: r["basics"].update(headline="Data Scientist"))
    fingerprint = section(db_path)["hash"]

    result = approve(db_path, fingerprint)

    assert result["created"] and store.get_master_resume()["resume"]["basics"]["headline"] == "Data Scientist"
    assert not section(db_path)["approval"]["can_approve"]


def test_approving_a_draft_changed_after_opening_the_panel_is_refused(db_path, store):
    approved_then_draft(store, db_path, lambda r: r["basics"].update(headline="Data Scientist"))
    fingerprint = section(db_path)["hash"]
    other = fictitious_resume()
    other["basics"]["headline"] = "Outra versão"
    store.save_master_draft(other, overwrite=True)

    with pytest.raises(Exception, match="(?i)recarregue"):
        approve(db_path, fingerprint)
    assert store.get_master_resume()["resume"]["basics"]["headline"] != "Outra versão"
