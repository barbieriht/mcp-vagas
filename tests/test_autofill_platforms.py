"""Extensão do Chrome: aprovação por plataforma (InHire, Cornerstone, Workday...), reconhecimento das caixas de
privacidade e o que o host registra do LinkedIn Easy Apply."""

import json

import pytest

from test_sensitive import FakeBackend
from vagas import config
from vagas.autofill import (DEFAULT_PLATFORMS, Applications, Approvals, Autofill, classify_consent, effective_platforms,
                            resolve_origin)
from vagas.db import connect
from vagas.repo import Repo
from vagas.resume_repo import ResumeStore
from vagas.sensitive import Vault
from resume_fixture import fictitious_resume

INHIRE = "Ao fornecer seus dados pessoais, você concorda com o que está descrito nesta Política de Privacidade, " \
         "inclusive, para que possam desempenhar soluções voltadas à diversidade."
ORACLE = "I agree with my personal data being processed in line with the privacy notice"
BRADESCO = "Autorizo o Bradesco a tratar meus dados pessoais para fins de recrutamento, nos termos da Lei Geral de " \
           "Proteção de Dados (LGPD). Concordo"
NOTICE = "Li e aceito o aviso de privacidade"


@pytest.mark.parametrize("text", [INHIRE, ORACLE, BRADESCO, NOTICE,
                                  "I consent to the processing of my personal data for recruitment purposes"])
def test_privacy_consents_are_recognized_in_portuguese_and_english(text):
    assert classify_consent(text) == "termos"


@pytest.mark.parametrize("text", ["Quero receber ofertas e novidades de marketing",
                                  "Assinar a newsletter semanal",
                                  "I'd like to receive updates about new job opportunities"])
def test_marketing_newsletter_and_job_alerts_are_never_consents(text):
    assert classify_consent(text) is None


@pytest.mark.parametrize("host, key", [
    ("cielo.inhire.app", "inhire.app"), ("dataside.inhire.app", "inhire.app"), ("bradesco.csod.com", "csod.com"),
    ("empresa.wd5.myworkdayjobs.com", "myworkdayjobs.com"), ("pdg-it.factorialhr.com.br", "factorialhr.com.br"),
    ("acme.recruitee.com", "recruitee.com"), ("minervatech.gupy.io", "gupy.io"),
])
def test_one_approval_covers_every_company_of_a_default_platform(host, key):
    origin = resolve_origin(f"https://{host}/vagas/1", {}, [], effective_platforms(""))

    assert origin.key == key and origin.remember


@pytest.mark.parametrize("url, key", [
    ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse.io"), ("https://jobs.lever.co/acme/1", "lever.co"),
    ("https://jobs.smartrecruiters.com/Acme/1", "smartrecruiters.com"),
])
def test_path_platforms_are_approved_as_a_whole_too(url, key):
    assert resolve_origin(url, {}, [], effective_platforms("")).key == key


@pytest.mark.parametrize("host", ["inhire.app.evil.com", "evilinhire.app", "gupy.io.example.com", "csod.com.evil.io"])
def test_lookalike_domains_never_match_a_platform(host):
    with pytest.raises(Exception, match="não é um site de vagas confiável"):
        resolve_origin(f"https://{host}/vagas/1", {}, [], effective_platforms(""))


def test_the_default_list_keeps_what_the_user_configured_and_can_be_trimmed():
    assert set(DEFAULT_PLATFORMS) <= set(effective_platforms("gupy.io"))
    assert "solides.com.br" not in DEFAULT_PLATFORMS  # sem um formato confirmado de candidatura multiempresa
    trimmed = effective_platforms("-csod.com, recruitee.com")
    assert "csod.com" not in trimmed and "inhire.app" in trimmed
    assert config.clean("autofill_platforms", "-csod.com, inhire.app") == "-csod.com, inhire.app"


def test_white_label_sites_keep_the_approval_per_host():
    # Oracle Recruiting em domínio da própria empresa: não há domínio comum, então nada de aprovação por plataforma.
    origin = resolve_origin("https://explore-jobs.ciklum.com/en/sites/ciklum-career/job/5130/apply/email",
                            {"ciklum.com": "Ciklum"}, [], effective_platforms(""))

    assert origin.key == "ciklum.com" and origin.label == "Ciklum"


# --- uma aprovação vale para documentos, termos e currículo em toda a plataforma ------------------

@pytest.fixture
def host(db_path, tmp_path):
    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    vault.set("cpf", "529.982.247-25")
    apps = Applications(db_path)
    return Autofill(vault, Approvals(tmp_path / "aprovacoes.json"), log_path=tmp_path / "autofill.log",
                    open_sites=apps.sites, extra_domains=lambda: [], resumes=apps.with_resumes,
                    platforms=lambda: effective_platforms(""), status_path=tmp_path / "autofill_status.json")


def with_resume(db_path, tmp_path, company, url, form_url=None):
    conn = connect(db_path)
    store = ResumeStore(conn, tmp_path / "curriculo.yaml")
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    app = Repo(conn).add_application(company=company, role="Cientista de Dados", source="linkedin", url=url,
                                     status="a_aplicar")["application"]
    created = store.create_tailored_resume({"label": company, "sections": [{"section": "experience"}]},
                                           tmp_path / "out", application_id=app["id"], form_url=form_url)
    conn.close()
    return app, created


CPF = {"id": "c", "text": "CPF", "attrs": "cpf"}
PRIVACY = {"id": "p", "kind": "checkbox", "text": INHIRE}
RESUME = {"id": "f", "kind": "file", "text": "Anexe seu currículo", "accept": ".pdf"}


def test_after_one_company_of_inhire_another_one_is_filled_without_asking(host, db_path, tmp_path):
    with_resume(db_path, tmp_path, "Dataside", "https://www.linkedin.com/jobs/view/4489292241/",
                form_url="https://dataside.inhire.app/vagas/b74f/cientista")
    first = host.handle({"url": "https://cielo.inhire.app/vagas/1", "fields": [CPF], "confirm": "always"})

    second = host.handle({"url": "https://dataside.inhire.app/vagas/b74f/cientista", "fields": [CPF, PRIVACY, RESUME],
                          "confirm": None})

    assert first["status"] == "filled" and first["label"] == "inhire.app (todas as empresas)"
    assert second["status"] == "filled" and set(second["values"]) == {"c", "p", "f"}


# --- LinkedIn Easy Apply ------------------------------------------------------------------------

@pytest.mark.parametrize("page", [
    "https://www.linkedin.com/jobs/view/4488199004/",
    "https://www.linkedin.com/jobs/view/4488199004",
    "https://www.linkedin.com/jobs/view/4488199004/?companyName=TCS&trackingId=abc%3D%3D&applicantTrackingSystemName=x",
    "https://www.linkedin.com/jobs/search-results/?currentJobId=4488199004&keywords=data",
    "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4488199004",
    "https://www.linkedin.com/jobs/view/4488199004/apply/?openSDUIApplyFlow=true",
])
def test_the_easy_apply_page_is_matched_by_the_linkedin_job_id(host, db_path, tmp_path, page):
    app, created = with_resume(db_path, tmp_path, "Tata Consultancy Services",
                               "https://linkedin.com/jobs/view/4488199004",
                               form_url="https://www.linkedin.com/jobs/view/4488199004/")

    asked = host.handle({"url": page, "fields": [RESUME], "confirm": None})

    assert [r["application_id"] for r in asked["resumes"]] == [app["id"]]


def test_the_host_records_the_linkedin_job_and_the_resume_outcome(host, db_path, tmp_path):
    with_resume(db_path, tmp_path, "TCS", "https://linkedin.com/jobs/view/4488199004")

    host.handle({"url": "https://www.linkedin.com/jobs/view/4488199004/?trackingId=x", "fields": [RESUME],
                 "confirm": "once", "version": "1.4.0"})

    entry = json.loads((tmp_path / "autofill_status.json").read_text(encoding="utf-8"))["recent"][0]
    assert entry["host"] == "www.linkedin.com" and entry["job"] == "4488199004" and entry["resume"] == "anexado"


def test_a_resume_too_big_is_recorded_instead_of_failing_silently(db_path, tmp_path):
    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    apps = Applications(db_path)
    small = Autofill(vault, Approvals(tmp_path / "aprovacoes.json"), log_path=tmp_path / "autofill.log",
                     open_sites=apps.sites, extra_domains=lambda: [], resumes=apps.with_resumes, max_file_bytes=10,
                     status_path=tmp_path / "autofill_status.json")
    with_resume(db_path, tmp_path, "TCS", "https://linkedin.com/jobs/view/4488199004")

    response = small.handle({"url": "https://www.linkedin.com/jobs/view/4488199004/", "fields": [RESUME],
                             "confirm": "once"})

    entry = json.loads((tmp_path / "autofill_status.json").read_text(encoding="utf-8"))["recent"][0]
    assert response["warnings"] and entry["resume"] == "grande_demais"


def test_a_probe_from_the_easy_apply_modal_is_recorded(host):
    probe = {"dialog": True, "file_inputs": 0, "shadow_roots": 2, "frames": 1}

    host.handle({"url": "https://www.linkedin.com/jobs/view/4488199004/", "fields": [], "probe": probe})

    entry = host.status.read()["recent"][0]
    assert entry["probe"] == probe and entry["job"] == "4488199004"
