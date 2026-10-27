import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore

SELECTION = {"label": "Nubank", "sections": [{"section": "experience"}]}


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return Repo(conn)


@pytest.fixture
def store(conn, tmp_path):
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    s.save_master_draft(fictitious_resume())
    s.approve_master()
    return s


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "out"


def new_application(repo, **overrides):
    fields = dict(company="Nubank", role="Data Scientist", source="linkedin")
    fields.update(overrides)
    return repo.add_application(**fields)


def test_tailored_resume_can_be_linked_on_creation(repo, store, out_dir):
    app = new_application(repo)["application"]

    resume = store.create_tailored_resume(SELECTION, out_dir, application_id=app["id"])

    assert store.get_resume(resume["id"])["application_id"] == app["id"]
    assert [r["id"] for r in repo.get_history(app["id"])["resumes"]] == [resume["id"]]


def test_linking_to_unknown_application_is_rejected_before_generating(store, out_dir):
    with pytest.raises(VagasError, match="999"):
        store.create_tailored_resume(SELECTION, out_dir, application_id=999)
    assert store.list_resumes() == []
    assert not out_dir.exists()


def test_add_application_links_resume(repo, store, out_dir):
    resume = store.create_tailored_resume(SELECTION, out_dir)

    app = new_application(repo, resume_id=resume["id"])["application"]

    history = repo.get_history(app["id"])
    assert history["resumes"] == [{
        "id": resume["id"], "label": "Nubank", "pdf_path": resume["path"],
        "created_at": store.get_resume(resume["id"])["created_at"],
    }]


def test_duplicate_application_does_not_link_resume(repo, store, out_dir):
    first = new_application(repo, url="https://x.com/1")["application"]
    resume = store.create_tailored_resume(SELECTION, out_dir)

    again = new_application(repo, url="https://x.com/1", resume_id=resume["id"])

    assert again["created"] is False
    assert repo.get_history(first["id"])["resumes"] == []
    assert store.get_resume(resume["id"])["application_id"] is None


def test_update_application_links_resume_without_other_changes(repo, store, out_dir):
    app = new_application(repo, status="pendente_usuario", pending="CPF")["application"]
    resume = store.create_tailored_resume(SELECTION, out_dir)

    updated = repo.update_application(app["id"], resume_id=resume["id"])

    assert updated["status"] == "pendente_usuario"
    assert [r["id"] for r in repo.get_history(app["id"])["resumes"]] == [resume["id"]]


@pytest.mark.parametrize("call", ["add", "update"])
def test_unknown_resume_is_rejected(repo, call):
    with pytest.raises(VagasError, match="Currículo personalizado 999"):
        if call == "add":
            new_application(repo, resume_id=999)
        else:
            repo.update_application(new_application(repo)["application"]["id"], resume_id=999)


def test_resume_linked_to_another_application_is_rejected(repo, store, out_dir):
    a = new_application(repo, url="https://x.com/a")["application"]
    b = new_application(repo, url="https://x.com/b")["application"]
    resume = store.create_tailored_resume(SELECTION, out_dir, application_id=a["id"])

    with pytest.raises(VagasError, match=f"candidatura {a['id']}"):
        repo.update_application(b["id"], resume_id=resume["id"])


def test_relinking_to_same_application_is_harmless(repo, store, out_dir):
    app = new_application(repo)["application"]
    resume = store.create_tailored_resume(SELECTION, out_dir, application_id=app["id"])

    repo.update_application(app["id"], resume_id=resume["id"])

    assert len(repo.get_history(app["id"])["resumes"]) == 1


def test_history_lists_all_linked_resumes_oldest_first(repo, store, out_dir):
    app = new_application(repo)["application"]
    first = store.create_tailored_resume(SELECTION, out_dir, application_id=app["id"])
    second = store.create_tailored_resume(SELECTION, out_dir, application_id=app["id"])

    assert [r["id"] for r in repo.get_history(app["id"])["resumes"]] == [first["id"], second["id"]]


def test_list_resumes_filters_by_application(repo, store, out_dir):
    app = new_application(repo)["application"]
    linked = store.create_tailored_resume(SELECTION, out_dir, application_id=app["id"])
    store.create_tailored_resume(SELECTION, out_dir)

    assert [r["id"] for r in store.list_resumes(application_id=app["id"])] == [linked["id"]]
    assert len(store.list_resumes()) == 2
