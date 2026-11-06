import io
import json
import struct

import pytest

from test_sensitive import FakeBackend
from vagas.autofill import Approvals, Autofill, classify, classify_consent, format_value, resolve_origin
from vagas.autofill_host import read_message, serve, write_message
from vagas.repo import VagasError
from vagas.sensitive import Vault

CPF = "52998224725"


@pytest.fixture
def vault(tmp_path):
    v = Vault(tmp_path / "cofre.json", FakeBackend())
    v.set("cpf", "529.982.247-25")
    v.set("rg", "12.345.678-9")
    return v


@pytest.fixture
def autofill(vault, tmp_path):
    return Autofill(vault, Approvals(tmp_path / "aprovacoes.json"), log_path=tmp_path / "autofill.log",
                    open_sites=lambda: {"empresa.com.br": "Empresa X"}, extra_domains=lambda: ["meuats.com"])


def request(url="https://acme.gupy.io/candidates/jobs/1/apply", confirm=None, fields=None):
    fields = fields if fields is not None else [{"id": "a", "text": "CPF *"}, {"id": "b", "text": "RG"},
                                                 {"id": "c", "text": "Nome completo"}]
    return {"url": url, "fields": fields, "confirm": confirm}


@pytest.mark.parametrize("text, expected", [
    ("CPF *", "cpf"), ("Número do CPF", "cpf"), ("cpf_candidato", "cpf"), ("Informe seu CPF (somente números)", "cpf"),
    ("RG", "rg"), ("Número do RG", "rg"), ("Carteira de identidade", "rg"), ("Registro Geral", "rg"),
    ("Órgão emissor do RG", "rg_orgao_emissor"), ("Orgão expedidor", "rg_orgao_emissor"),
    ("CNH", "cnh"), ("Número da carteira de habilitação", "cnh"), ("PIS/PASEP", "pis"), ("NIS", "pis"),
    ("CTPS", "ctps"), ("Número da carteira de trabalho", "ctps"), ("Título de eleitor", "titulo_eleitor"),
    ("Passaporte", "passaporte"), ("Passport number", "passaporte"), ("Nome da mãe", "nome_mae"),
    ("Mother's name", "nome_mae"),
])
def test_document_fields_are_recognized_by_their_label(text, expected):
    assert classify(text) == expected


@pytest.mark.parametrize("text", [
    "Nome completo", "Identidade de gênero", "Data de emissão do RG", "Validade da CNH", "Categoria da CNH",
    "Possui CNH?", "Série da CTPS", "Zona eleitoral", "Seção do título de eleitor", "UF do RG",
    "Nome do pai", "Anexar foto do RG", "Data de expedição", "", "Programa de integração social (descreva)",
    "E-mail", "Telefone", "Cargo pretendido", "Org",
])
def test_other_fields_are_left_alone(text):
    assert classify(text) is None


@pytest.mark.parametrize("field, hint, expected", [
    ("cpf", {"placeholder": "000.000.000-00"}, "529.982.247-25"),
    ("cpf", {"maxlength": 14}, "529.982.247-25"),
    ("cpf", {"maxlength": 11}, CPF),
    ("cpf", {"placeholder": "Somente números"}, CPF),
    ("cpf", {}, CPF),
    ("rg", {"placeholder": "00.000.000-0"}, "12.345.678-9"),
])
def test_values_follow_the_mask_of_the_field(field, hint, expected):
    stored = {"cpf": CPF, "rg": "12.345.678-9"}[field]
    assert format_value(field, stored, hint) == expected


@pytest.mark.parametrize("url, key, label, remember", [
    ("https://acme.gupy.io/candidates/jobs/1/apply", "acme.gupy.io", "acme", True),
    ("https://empresa.wd1.myworkdayjobs.com/pt-BR/careers/job/1/apply", "empresa.wd1.myworkdayjobs.com", "empresa", True),
    ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse.io/acme", "acme", True),
    ("https://jobs.lever.co/acme/123/apply", "lever.co/acme", "acme", True),
    ("https://jobs.ashbyhq.com/Acme/123", "ashbyhq.com/acme", "Acme", True),
    ("https://careers.empresa.com.br/vaga/1", "empresa.com.br", "Empresa X", True),
    ("https://app.meuats.com/x", "meuats.com", "meuats.com", True),
    ("https://www.linkedin.com/jobs/view/4012345678/", "linkedin.com/vaga/4012345678", "LinkedIn", False),
    ("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4012345678", "linkedin.com/vaga/4012345678",
     "LinkedIn", False),
    ("https://br.indeed.com/viewjob?jk=abc123def", "indeed.com/vaga/abc123def", "Indeed", False),
    ("https://www.glassdoor.com.br/job-listing/x?jl=1009", "glassdoor.com.br/vaga/1009", "Glassdoor", False),
])
def test_origin_identifies_the_company_or_the_job(url, key, label, remember):
    origin = resolve_origin(url, open_sites={"empresa.com.br": "Empresa X"}, extra_domains=["meuats.com"])

    assert (origin.key, origin.label, origin.remember) == (key, label, remember)


@pytest.mark.parametrize("url, message", [
    ("http://acme.gupy.io/apply", "https"),
    ("https://golpe.com/apply", "não é um site de vagas"),
    ("https://acme.gupy.io.golpe.com/apply", "não é um site de vagas"),
    ("https://linkedin.com.golpe.net/apply", "não é um site de vagas"),
    ("nada", "https"),
])
def test_untrusted_pages_are_refused(url, message):
    with pytest.raises(VagasError, match=message):
        resolve_origin(url, open_sites={}, extra_domains=[])


def test_first_use_of_a_company_asks_for_confirmation_without_revealing_values(autofill, tmp_path):
    response = autofill.handle(request())

    assert response["status"] == "confirm"
    assert response["origin"] == {"key": "acme.gupy.io", "label": "acme", "host": "acme.gupy.io", "remember": True}
    assert response["documents"] == ["CPF", "RG"] and response["terms"] == []
    assert CPF not in json.dumps(response) and "12.345.678-9" not in json.dumps(response)
    assert not (tmp_path / "autofill.log").exists()


def test_always_is_remembered_for_the_company(autofill, tmp_path):
    first = autofill.handle(request(confirm="always"))
    later = autofill.handle(request(url="https://acme.gupy.io/candidates/jobs/2/apply"))
    other = autofill.handle(request(url="https://outra.gupy.io/candidates/jobs/2/apply"))

    assert first == {"status": "filled", "values": {"a": CPF, "b": "12.345.678-9"}, "label": "acme"}
    assert later["status"] == "filled"
    assert other["status"] == "confirm"
    assert [a["key"] for a in Approvals(tmp_path / "aprovacoes.json").list()] == ["acme.gupy.io"]


def test_once_fills_without_remembering(autofill):
    assert autofill.handle(request(confirm="once"))["status"] == "filled"
    assert autofill.handle(request())["status"] == "confirm"


def test_aggregators_are_never_remembered(autofill, tmp_path):
    url = "https://www.linkedin.com/jobs/view/1/"

    response = autofill.handle(request(url=url, confirm="always"))

    assert response["status"] == "filled"
    assert autofill.handle(request(url=url))["status"] == "confirm"
    assert Approvals(tmp_path / "aprovacoes.json").list() == []


def test_use_is_logged_without_values(autofill, tmp_path):
    autofill.handle(request(confirm="once"))

    log = (tmp_path / "autofill.log").read_text(encoding="utf-8")
    entry = json.loads(log.splitlines()[0])
    assert entry["host"] == "acme.gupy.io" and entry["documents"] == ["CPF", "RG"] and entry["mode"] == "once"
    assert CPF not in log and "12.345.678-9" not in log


def test_untrusted_page_is_refused_even_when_confirmed(autofill):
    response = autofill.handle(request(url="https://golpe.com/form", confirm="always"))

    assert response["status"] == "refused" and "golpe.com" in response["reason"]


def test_nothing_to_fill(autofill, vault):
    assert autofill.handle(request(fields=[{"id": "c", "text": "Nome"}]))["status"] == "nothing"
    vault.remove("cpf")
    vault.remove("rg")
    assert autofill.handle(request(confirm="once"))["status"] == "nothing"


def test_fields_missing_from_the_vault_are_skipped(autofill, vault):
    vault.remove("rg")

    response = autofill.handle(request(confirm="once"))

    assert response["values"] == {"a": CPF}


def test_approvals_can_be_listed_and_revoked(tmp_path):
    approvals = Approvals(tmp_path / "aprovacoes.json")
    approvals.add("acme.gupy.io", "acme")
    approvals.add("lever.co/beta", "beta")

    assert approvals.remove("acme.gupy.io") is True
    assert approvals.remove("acme.gupy.io") is False
    assert [a["key"] for a in approvals.list()] == ["lever.co/beta"]
    approvals.clear()
    assert approvals.list() == []


def test_native_messaging_framing_round_trip():
    stream = io.BytesIO()
    write_message(stream, {"status": "ok", "texto": "ção"})
    stream.seek(0)

    assert struct.unpack("<I", stream.getvalue()[:4])[0] == len(stream.getvalue()) - 4
    assert read_message(stream) == {"status": "ok", "texto": "ção"}
    assert read_message(stream) is None


def test_host_answers_each_message_and_reports_errors(autofill):
    incoming = io.BytesIO()
    write_message(incoming, request(confirm="once"))
    incoming.write(struct.pack("<I", 5) + b"{nao]")
    incoming.seek(0)
    outgoing = io.BytesIO()

    serve(incoming, outgoing, autofill)

    outgoing.seek(0)
    assert read_message(outgoing)["status"] == "filled"
    assert read_message(outgoing)["status"] == "error"


TERMS = "Li e concordo com os Termos de Uso e a Política de Privacidade"


@pytest.mark.parametrize("text", [
    TERMS, "Aceito os termos e condições de uso", "Concordo com as Condições Gerais de Uso",
    "Declaro que li e aceito o Aviso de Privacidade", "Estou ciente do tratamento dos meus dados conforme a LGPD",
    "Autorizo o tratamento dos meus dados pessoais para este processo seletivo", "I agree to the Terms of Service",
    "I have read the Privacy Policy", "Aceito a Política de Proteção de Dados", "Termos de uso *",
])
def test_terms_and_privacy_consents_are_recognized(text):
    assert classify_consent(text) == "termos"


@pytest.mark.parametrize("text", [
    "Aceito receber novidades e ofertas por e-mail", "Quero receber comunicações por WhatsApp",
    "Autorizo compartilhar meus dados com empresas parceiras", "Aceito participar de outros processos seletivos",
    "Manter meu currículo no banco de talentos", "Declaro que não possuo parentes na empresa",
    "Declaro que as informações são verdadeiras", "Li e aceito os termos de uso e quero receber a newsletter",
    "Tenho disponibilidade para viagens", "Possuo CNH", "Sou pessoa com deficiência", "",
    "Aceito que meus dados sejam compartilhados com terceiros conforme a Política de Privacidade",
    "I agree to receive marketing emails",
])
def test_other_checkboxes_are_never_accepted(text):
    assert classify_consent(text) is None


def checkbox(text=TERMS, id="t"):
    return {"id": id, "kind": "checkbox", "text": text}


def test_terms_are_confirmed_with_their_text_and_checked(autofill, tmp_path):
    fields = [{"id": "a", "text": "CPF"}, checkbox(), checkbox("Quero receber novidades", id="n")]

    asked = autofill.handle(request(fields=fields))
    filled = autofill.handle(request(fields=fields, confirm="once"))

    assert asked["status"] == "confirm" and asked["terms"] == [TERMS] and asked["documents"] == ["CPF"]
    assert filled["values"] == {"a": CPF, "t": True}
    entry = json.loads((tmp_path / "autofill.log").read_text(encoding="utf-8").splitlines()[0])
    assert entry["terms"] == [TERMS] and entry["host"] == "acme.gupy.io"


def test_terms_alone_still_ask_and_follow_the_same_site_rule(autofill):
    assert autofill.handle(request(fields=[checkbox()]))["status"] == "confirm"
    assert autofill.handle(request(fields=[checkbox()], confirm="once"))["values"] == {"t": True}
    assert autofill.handle(request(url="https://golpe.com/x", fields=[checkbox()], confirm="once"))["status"] == "refused"


def test_an_approval_given_for_documents_only_asks_again_for_terms(autofill):
    autofill.handle(request(confirm="always"))

    documents_again = autofill.handle(request())
    with_terms = autofill.handle(request(fields=[{"id": "a", "text": "CPF"}, checkbox()]))
    autofill.handle(request(fields=[checkbox()], confirm="always"))
    later = autofill.handle(request(fields=[{"id": "a", "text": "CPF"}, checkbox()]))

    assert documents_again["status"] == "filled"
    assert with_terms["status"] == "confirm"
    assert later["status"] == "filled" and later["values"] == {"a": CPF, "t": True}


def test_checkbox_labels_never_become_documents(autofill):
    response = autofill.handle(request(fields=[checkbox("CPF"), {"id": "x", "kind": "checkbox", "text": "RG"}],
                                       confirm="once"))

    assert response["status"] == "nothing"
