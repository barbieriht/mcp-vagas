import itertools
import sqlite3

import pytest
import yaml

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore


@pytest.fixture
def draft_path(tmp_path):
    return tmp_path / "curriculo.yaml"


@pytest.fixture
def store(db_path, draft_path):
    ticks = itertools.count()
    conn = connect(db_path)
    yield ResumeStore(conn, draft_path, now=lambda: f"2026-10-27T12:00:{next(ticks):02d}+00:00")
    conn.close()


def test_save_draft_writes_readable_yaml(store, draft_path):
    result = store.save_master_draft(fictitious_resume())

    assert result["path"] == str(draft_path)
    text = draft_path.read_text(encoding="utf-8")
    assert text.startswith("basics:")
    assert "Fulana de Tal" in text
    assert yaml.safe_load(text)["experience"][0]["paragraphs"][0]["text"].startswith("Coordinated")


def test_draft_round_trips_long_paragraphs_and_symbols(store, draft_path):
    resume = fictitious_resume()
    store.save_master_draft(resume)

    loaded = yaml.safe_load(draft_path.read_text(encoding="utf-8"))

    assert loaded["experience"][0]["paragraphs"] == resume["experience"][0]["paragraphs"]
    assert loaded["skills"][0]["terms"] == ["Python", "SQL", "C++", "C#"]


def test_same_company_roles_are_distinct_items(store):
    store.save_master_draft(fictitious_resume())
    store.approve_master()

    experience = store.get_master_resume()["resume"]["experience"]

    assert [(e["company"], e["id"]) for e in experience] == [
        ("Acme Analytics", "exp-acme-tech-lead"),
        ("Acme Analytics", "exp-acme-analyst"),
    ]


def _without_title(r):
    del r["experience"][1]["title"]


def _duplicate_id(r):
    r["experience"][1]["paragraphs"][0]["id"] = "exp-acme-tech-lead-p1"


def _paragraph_without_id(r):
    del r["experience"][0]["paragraphs"][1]["id"]


def _bad_slug(r):
    r["skills"][0]["id"] = "Skills Languages"


def _unknown_field(r):
    r["experience"][0]["salary"] = "100k"


def _without_name(r):
    del r["basics"]["name"]


@pytest.mark.parametrize(
    "break_it, expected",
    [
        (_without_title, "experience.1.title"),
        (_duplicate_id, "exp-acme-tech-lead-p1"),
        (_paragraph_without_id, "experience.0.paragraphs.1.id"),
        (_bad_slug, "Skills Languages"),
        (_unknown_field, "experience.0.salary"),
        (_without_name, "basics.name"),
    ],
)
def test_invalid_structure_points_at_the_item(store, draft_path, break_it, expected):
    resume = fictitious_resume()
    break_it(resume)

    with pytest.raises(VagasError, match=expected.replace(".", r"\.")):
        store.save_master_draft(resume)
    assert not draft_path.exists()


def test_approve_promotes_hand_edited_draft(store, draft_path):
    store.save_master_draft(fictitious_resume())
    edited = draft_path.read_text(encoding="utf-8").replace("Quantitative Analyst", "Quant Analyst")
    draft_path.write_text(edited, encoding="utf-8")

    approved = store.approve_master()

    assert approved["created"] is True
    master = store.get_master_resume()
    assert master["version_id"] == approved["version_id"]
    assert master["resume"]["experience"][1]["title"] == "Quant Analyst"


def test_approve_revalidates_hand_edits(store, draft_path):
    store.save_master_draft(fictitious_resume())
    draft_path.write_text(
        draft_path.read_text(encoding="utf-8").replace("id: exp-acme-analyst-p1", "id: exp-acme-tech-lead-p1"),
        encoding="utf-8",
    )

    with pytest.raises(VagasError, match="exp-acme-tech-lead-p1"):
        store.approve_master()
    with pytest.raises(VagasError, match="approve_master"):
        store.get_master_resume()


def test_approve_with_broken_yaml_is_a_readable_error(store, draft_path):
    draft_path.write_text("basics: [unclosed", encoding="utf-8")

    with pytest.raises(VagasError, match="YAML"):
        store.approve_master()


def test_approve_without_draft_is_a_readable_error(store):
    with pytest.raises(VagasError, match="save_master_draft"):
        store.approve_master()


def test_approving_same_content_twice_does_not_duplicate_version(store):
    store.save_master_draft(fictitious_resume())
    first = store.approve_master()

    second = store.approve_master()

    assert second["created"] is False
    assert second["version_id"] == first["version_id"]


def test_latest_approved_version_wins(store, draft_path):
    store.save_master_draft(fictitious_resume())
    first = store.approve_master()
    resume = fictitious_resume()
    resume["basics"]["headline"] = "AI Engineer"
    store.save_master_draft(resume)

    second = store.approve_master()

    master = store.get_master_resume()
    assert second["version_id"] != first["version_id"]
    assert (master["version_id"], master["resume"]["basics"]["headline"]) == (second["version_id"], "AI Engineer")


def test_get_without_approved_resume_says_what_to_do(store):
    with pytest.raises(VagasError, match="save_master_draft.*approve_master"):
        store.get_master_resume()


def test_save_does_not_overwrite_unapproved_hand_edits(store, draft_path):
    store.save_master_draft(fictitious_resume())
    draft_path.write_text(draft_path.read_text(encoding="utf-8") + "# minha edição\n", encoding="utf-8")
    edits = draft_path.read_text(encoding="utf-8")

    with pytest.raises(VagasError, match="overwrite"):
        store.save_master_draft(fictitious_resume())
    assert draft_path.read_text(encoding="utf-8") == edits

    store.save_master_draft(fictitious_resume(), overwrite=True)
    assert "# minha edição" not in draft_path.read_text(encoding="utf-8")


def test_save_may_replace_draft_equal_to_approved_version(store):
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    resume = fictitious_resume()
    resume["basics"]["headline"] = "AI Engineer"

    store.save_master_draft(resume)

    store.approve_master()
    assert store.get_master_resume()["resume"]["basics"]["headline"] == "AI Engineer"


def test_migration_from_v1_backs_up_and_adds_master_resumes(tmp_path):
    path = tmp_path / "v1.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE applications (id INTEGER PRIMARY KEY)")
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()

    conn = connect(path)

    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 2
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'master_resumes'").fetchone()
    assert list(tmp_path.glob("v1.db.bak-v1-*"))


def test_save_may_replace_its_own_unedited_draft(store):
    store.save_master_draft(fictitious_resume())
    resume = fictitious_resume()
    resume["basics"]["headline"] = "AI Engineer"

    store.save_master_draft(resume)

    store.approve_master()
    assert store.get_master_resume()["resume"]["basics"]["headline"] == "AI Engineer"
