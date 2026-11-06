import base64
import json
from pathlib import Path

import pytest

from resume_fixture import fictitious_resume
from test_sensitive import FakeBackend
from vagas.autofill import Applications, Approvals, Autofill, classify_upload
from vagas.db import connect
from vagas.repo import Repo
from vagas.resume_repo import ResumeStore
from vagas.sensitive import Vault

SELECTION = {"label": "Acme", "sections": [{"section": "experience"}]}


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def store(conn, tmp_path):
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    s.save_master_draft(fictitious_resume())
    s.approve_master()
    return s


@pytest.fixture
def make(conn, store, tmp_path):
    def make(url, company="Acme", role="Data Scientist", status="a_aplicar", resume=True):
        extra = {"pending": "x"} if status == "pendente_usuario" else {}
        app = Repo(conn).add_application(company=company, role=role, source="outro", url=url, status=status,
                                         **extra)["application"]
        if resume:
            created = store.create_tailored_resume(SELECTION, tmp_path / "out", application_id=app["id"])
            app["pdf"] = Path(created["path"])
        return app
    return make


@pytest.fixture
def autofill(db_path, tmp_path):
    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    vault.set("cpf", "529.982.247-25")
    apps = Applications(db_path)
    return Autofill(vault, Approvals(tmp_path / "aprovacoes.json"), log_path=tmp_path / "autofill.log",
                    open_sites=apps.sites, extra_domains=lambda: [], resumes=apps.with_resumes)


def upload(id="f", text="Anexe seu currículo", accept=""):
    return {"id": id, "kind": "file", "text": text, "accept": accept}


def ask(autofill, url, fields=None, **extra):
    return autofill.handle({"url": url, "fields": fields or [upload()], "confirm": None, **extra})


@pytest.mark.parametrize("text", ["Currículo *", "Anexe seu currículo (PDF, até 5 MB)", "Upload resume", "Resume/CV",
                                  "Envie seu CV", "curriculum_vitae", "Anexar currículo arquivo"])
def test_resume_uploads_are_recognized(text):
    assert classify_upload(text) == "curriculo"


@pytest.mark.parametrize("text", ["Carta de apresentação", "Cover letter", "Foto de perfil", "Portfólio",
                                  "Anexe seu currículo ou portfólio", "Certificado de conclusão", "Documento com foto",
                                  "Comprovante de residência", "Histórico escolar", "Anexo", ""])
def test_other_uploads_are_left_alone(text):
    assert classify_upload(text) is None


def test_resume_of_the_application_is_attached_from_where_it_was_saved(autofill, make, tmp_path):
    app = make("https://acme.gupy.io/jobs/123")
    url = "https://acme.gupy.io/candidates/jobs/123/apply?jobBoardSource=gupy_public_page"

    asked = ask(autofill, url)
    filled = ask(autofill, url, confirm="once")

    assert asked["status"] == "confirm"
    assert asked["resumes"] == [{"application_id": app["id"], "label": "Data Scientist — Acme", "name": app["pdf"].name}]
    sent = filled["values"]["f"]
    assert sent["name"] == app["pdf"].name and sent["type"] == "application/pdf"
    assert base64.b64decode(sent["data"]) == app["pdf"].read_bytes()
    entry = json.loads((tmp_path / "autofill.log").read_text(encoding="utf-8").splitlines()[0])
    assert entry["resume"] == {"application_id": app["id"], "name": app["pdf"].name}


@pytest.mark.parametrize("job_url, page_url", [
    ("https://www.linkedin.com/jobs/view/4012345678/", "https://www.linkedin.com/jobs/search/?currentJobId=4012345678"),
    ("https://jobs.lever.co/acme/5f1c-aa", "https://jobs.lever.co/acme/5f1c-aa/apply"),
    ("https://careers.empresa.com.br/vagas/9", "https://careers.empresa.com.br/vagas/9"),
])
def test_the_page_is_matched_to_its_application(autofill, make, job_url, page_url):
    app = make(job_url)
    make("https://acme.gupy.io/jobs/555", company="Outra")

    asked = ask(autofill, page_url)

    assert [r["application_id"] for r in asked["resumes"]] == [app["id"]]


def test_several_applications_of_the_same_company_ask_which_resume_even_when_approved(autofill, make):
    first = make("https://careers.empresa.com.br/vagas/1", company="Empresa", role="DS")
    second = make("https://careers.empresa.com.br/vagas/2", company="Empresa", role="MLE")
    page = "https://careers.empresa.com.br/candidatura/form"
    ask(autofill, page, fields=[upload()], confirm="always", resume_application_id=first["id"])

    asked = ask(autofill, page)
    chosen = ask(autofill, page, resume_application_id=second["id"])

    assert asked["status"] == "confirm"
    assert {r["application_id"] for r in asked["resumes"]} == {first["id"], second["id"]}
    assert chosen["status"] == "filled" and chosen["values"]["f"]["name"] == second["pdf"].name


def test_a_choice_outside_the_candidates_is_refused(autofill, make):
    make("https://careers.empresa.com.br/vagas/1")
    other = make("https://acme.gupy.io/jobs/2", company="Outra")

    response = ask(autofill, "https://careers.empresa.com.br/vagas/1", confirm="once", resume_application_id=other["id"])

    assert response["status"] == "nothing"


def test_an_approval_without_the_resume_asks_again(autofill, make):
    make("https://acme.gupy.io/jobs/123")
    url = "https://acme.gupy.io/candidates/jobs/123/apply"
    autofill.handle({"url": url, "fields": [{"id": "c", "text": "CPF"}], "confirm": "always"})

    with_resume = ask(autofill, url, fields=[{"id": "c", "text": "CPF"}, upload()])
    ask(autofill, url, confirm="always")
    later = ask(autofill, url, fields=[{"id": "c", "text": "CPF"}, upload()])

    assert with_resume["status"] == "confirm"
    assert later["status"] == "filled" and set(later["values"]) == {"c", "f"}


@pytest.mark.parametrize("status, resume", [("aplicada", True), ("descartada", True), ("a_aplicar", False)])
def test_only_open_applications_with_a_tailored_resume(autofill, make, conn, status, resume):
    app = make("https://acme.gupy.io/jobs/123", resume=resume)
    if status != "a_aplicar":
        Repo(conn).update_application(app["id"], status=status,
                                      **({"discard_reason": "x"} if status == "descartada" else {}))

    assert ask(autofill, "https://acme.gupy.io/candidates/jobs/123/apply")["status"] == "nothing"


def test_the_latest_resume_of_the_application_wins(autofill, make, store, tmp_path):
    app = make("https://acme.gupy.io/jobs/123")
    newer = Path(store.create_tailored_resume({**SELECTION, "label": "Acme v2"}, tmp_path / "out",
                                              application_id=app["id"])["path"])

    response = ask(autofill, "https://acme.gupy.io/jobs/123", confirm="once")

    assert response["values"]["f"]["name"] == newer.name


def test_fields_that_do_not_accept_pdf_and_missing_files_are_skipped(autofill, make):
    app = make("https://acme.gupy.io/jobs/123")
    url = "https://acme.gupy.io/jobs/123"

    assert ask(autofill, url, fields=[upload(accept=".doc,.docx")])["status"] == "nothing"
    assert ask(autofill, url, fields=[upload(accept=".pdf,.doc")])["status"] == "confirm"
    app["pdf"].unlink()
    assert ask(autofill, url)["status"] == "nothing"


def test_files_too_large_for_native_messaging_are_skipped_with_a_warning(make, db_path, tmp_path):
    make("https://acme.gupy.io/jobs/123")
    apps = Applications(db_path)
    small = Autofill(Vault(tmp_path / "c.json", FakeBackend()), Approvals(tmp_path / "a.json"), tmp_path / "l.log",
                     open_sites=apps.sites, extra_domains=lambda: [], resumes=apps.with_resumes, max_file_bytes=100)

    response = small.handle({"url": "https://acme.gupy.io/jobs/123", "fields": [upload()], "confirm": "once"})

    assert response["status"] == "nothing" and "grande demais" in response["warnings"][0]


def test_only_one_resume_field_gets_the_file(autofill, make):
    make("https://acme.gupy.io/jobs/123")

    response = ask(autofill, "https://acme.gupy.io/jobs/123", fields=[upload("a"), upload("b")], confirm="once")

    assert list(response["values"]) == ["a"]


def test_a_trusted_platform_never_offers_another_companys_resume(make, db_path, tmp_path):
    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    apps = Applications(db_path)
    autofill = Autofill(vault, Approvals(tmp_path / "aprovacoes.json"), log_path=tmp_path / "autofill.log",
                        open_sites=apps.sites, extra_domains=lambda: [], resumes=apps.with_resumes,
                        platforms=lambda: ["gupy.io"])
    acme = make("https://acme.gupy.io/jobs/111")
    make("https://outra.gupy.io/jobs/222", company="Outra")

    response = ask(autofill, "https://acme.gupy.io/candidates/jobs/333/apply")

    assert response["origin"]["key"] == "gupy.io"
    assert [r["application_id"] for r in response["resumes"]] == [acme["id"]]
