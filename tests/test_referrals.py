"""Indicações: quem indicou o usuário em cada empresa. Respondem "Foi indicado?" nas vagas dessa empresa, põem as
vagas dela primeiro na lista de trabalho e nunca levam o contato de terceiros a eventos, logs ou ao CSV."""

import logging

import pytest
from mcp import Client

from test_sensitive import FakeBackend
from test_triage import BAD, approved, conn, fetcher, files, gupy, market, triage  # noqa: F401 (fixtures)
from vagas import settings_form
from vagas.export import export_csv
from vagas.form_answers import resolve
from vagas.profile_fields import ProfileFiles
from vagas.referrals import ReferralStore, fits
from vagas.repo import Repo, VagasError
from vagas.sensitive import Vault
from vagas.server import build_server

pytestmark = pytest.mark.anyio

EMAIL, PHONE = "ana.lima@example.com", "+55 11 91234-5678"

PERFIL = """\
# Dados para formulários

## Respostas padrão
- Foi indicado por alguém da empresa: Não

## Outros campos de formulário
- CPF: informar manualmente
"""


@pytest.fixture
def store(conn):  # noqa: F811
    return ReferralStore(conn)


@pytest.fixture
def skill(tmp_path, monkeypatch):
    folder = tmp_path / "skill"
    folder.mkdir()
    (folder / "perfil.md").write_text(PERFIL, encoding="utf-8")
    (folder / "perfil.example.md").write_text(PERFIL, encoding="utf-8")
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(folder))
    return folder


# --- cadastro --------------------------------------------------------------------------------------

def test_a_referral_is_stored_and_the_same_person_is_updated(store):
    first = store.add("Itaú Unibanco S.A.", "Ana Lima", email=EMAIL, role="Analista de Dados", scope="dados, IA",
                      referred_on="2026-11-10")
    again = store.add("ITAU UNIBANCO", "ana lima", phone=PHONE, note="")

    assert first["created"] is True and again["created"] is False
    referral = again["referral"]
    assert referral["id"] == first["referral"]["id"]
    assert (referral["email"], referral["phone"], referral["role"], referral["referred_on"]) == (
        EMAIL, PHONE, "Analista de Dados", "2026-11-10")
    assert len(store.entries()) == 1


@pytest.mark.parametrize("fields, message", [
    ({"company": "", "name": "Ana"}, "company"),
    ({"company": "Itaú", "name": " "}, "name"),
    ({"company": "Itaú", "name": "Ana", "email": "ana"}, "E-mail"),
    ({"company": "Itaú", "name": "Ana", "phone": "123"}, "Telefone"),
    ({"company": "Itaú", "name": "Ana", "referred_on": "10/11/2026"}, "AAAA-MM-DD"),
])
def test_invalid_fields_say_what_to_fix(store, fields, message):
    with pytest.raises(VagasError, match=message):
        store.add(**fields)


def test_companies_match_normalized_by_whole_words(store):
    store.add("Itaú", "Ana Lima")
    store.add("Grupo Boticário", "Bruno Reis")

    assert [r["name"] for r in store.entries("Itaú Unibanco S.A.")] == ["Ana Lima"]
    assert [r["name"] for r in store.entries("boticario")] == ["Bruno Reis"]
    assert store.entries("Grupo Pão de Açúcar") == []  # só a palavra genérica em comum


def test_removing_needs_an_existing_id(store):
    referral = store.add("Itaú", "Ana Lima")["referral"]

    assert store.remove(referral["id"]) == {"removed": referral["id"]}
    with pytest.raises(VagasError, match="list_referrals"):
        store.remove(referral["id"])


@pytest.mark.parametrize("scope, role, ok", [
    (None, "Backend Engineer", True),
    ("dados, IA", "Cientista de Dados Pleno", True),
    ("dados, IA", "Engenheiro de IA", True),
    ("dados, IA", "Backend Engineer", False),
    ("Data Science", "Senior Data Scientist", False),  # termo inteiro, não pedaço de palavra
])
def test_the_scope_limits_the_roles(scope, role, ok):
    assert fits({"scope": scope}, role) is ok


# --- respostas de formulário -----------------------------------------------------------------------

def answer(skill, question, options, referrals, referral_id=None):
    profile = ProfileFiles(skill).get_profile(vault_fields=[])
    return resolve(profile, question, options, company="Itaú", referrals=referrals, referral_id=referral_id)


ANA = {"id": 1, "company": "Itaú", "name": "Ana Lima", "email": EMAIL, "role": "Analista de Dados"}
BRUNO = {"id": 2, "company": "Itaú", "name": "Bruno Reis", "scope": "jurídico"}


@pytest.mark.parametrize("question, options, expected", [
    ("Foi indicado?", ["Não", "Sim"], "Sim"),
    ("Alguém que trabalha nesta empresa indicou você para esta vaga?", ["Sim", "Não"], "Sim"),
    ("Were you referred by a current employee?", ["Yes", "No"], "Yes"),
    ("Nome do colaborador que indicou você", [], "Ana Lima"),
    ("E-mail de quem indicou", [], EMAIL),
    ("Referrer name", [], "Ana Lima"),
])
def test_a_registered_referral_answers_yes_and_gives_the_referrer(skill, question, options, expected):
    result = answer(skill, question, options, {"fits": [ANA], "other_scope": []})

    assert result == {"answer": expected, "source": {"kind": "indicacao", "referral_id": 1}}


def test_without_a_referral_at_the_company_the_profile_default_is_used(skill):
    result = answer(skill, "Foi indicado?", ["Não", "Sim"], {"fits": [], "other_scope": []})

    assert result["answer"] == "Não" and result["source"]["field"] == "Foi indicado por alguém da empresa"


def test_two_people_at_the_company_ask_which_one(skill):
    two = {"fits": [ANA, {**BRUNO, "scope": None}], "other_scope": []}

    blocked = answer(skill, "Foi indicado?", ["Sim", "Não"], two)
    chosen = answer(skill, "Nome de quem indicou", [], two, referral_id=2)

    assert blocked["blocked"] and [c["id"] for c in blocked["choices"]] == [1, 2]
    assert "email" not in blocked["choices"][0]  # o contato só sai quando o formulário pede
    assert chosen["answer"] == "Bruno Reis"


def test_a_referral_for_another_area_is_confirmed_first(skill):
    result = answer(skill, "Foi indicado?", ["Sim", "Não"], {"fits": [], "other_scope": [BRUNO]})

    assert result["blocked"] and result["choices"] == [{"id": 2, "name": "Bruno Reis", "scope": "jurídico"}]


@pytest.mark.parametrize("question, word", [("Telefone de quem indicou", "telefone"),
                                            ("Código de indicação", "código")])
def test_a_detail_that_is_not_registered_is_asked(skill, question, word):
    result = answer(skill, question, [], {"fits": [ANA], "other_scope": []})

    assert result["blocked"] and word in result["reason"]


# --- triagem e lista de trabalho -------------------------------------------------------------------

def test_triage_tells_the_referral_and_the_work_list_puts_it_first(triage, fetcher, conn, store):  # noqa: F811
    market(conn, 12000)
    plain = triage.triage_job(fetcher.add(gupy(1, company="Outra Empresa")))
    store.add("Acme", "Ana Lima", email=EMAIL)
    referred = triage.triage_job(fetcher.add(gupy(2, description=BAD)))

    assert any(r.startswith("Indicação na empresa: Ana Lima") for r in referred["reasons"])
    assert not any("Indicação" in r for r in plain["reasons"])
    assert not any(EMAIL in r for r in referred["reasons"])
    assert referred["application"]["match_score"] < plain["application"]["match_score"]  # a nota não muda
    listed = Repo(conn).list_applications(status="a_aplicar")["applications"]
    assert [a["id"] for a in listed] == [referred["application"]["id"], plain["application"]["id"]]
    assert listed[0]["referral"] is True and "referral" not in listed[1]


# --- privacidade -----------------------------------------------------------------------------------

def test_the_contact_never_reaches_events_logs_or_the_csv(triage, fetcher, conn, store, tmp_path, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    market(conn, 12000)
    store.add("Acme", "Ana Lima", email=EMAIL, phone=PHONE)
    result = triage.triage_job(fetcher.add(gupy(3)))
    Repo(conn).update_application(result["application"]["id"], note="indicada")

    exported = export_csv(Repo(conn), tmp_path / "csv")

    csv = open(exported["path"], encoding="utf-8-sig").read()
    events = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM events"))
    for secret in (EMAIL, PHONE):
        assert secret not in csv and secret not in events and secret not in caplog.text
    assert "referral" not in csv.splitlines()[0].split(";")


# --- pelo MCP e pelo painel ------------------------------------------------------------------------

async def test_the_tools_add_list_answer_and_remove(db_path, skill):
    server = build_server(db_path, vault=Vault(skill / "cofre.json", FakeBackend()))
    with _conn(db_path) as c:
        app = Repo(c).add_application("Itaú Unibanco S.A.", "Cientista de Dados", "gupy", status="a_aplicar")
    app = app["application"]
    async with Client(server) as client:
        added = (await client.call_tool("add_referral", {"company": "Itaú", "name": "Ana Lima", "email": EMAIL})
                 ).structured_content
        listed = (await client.call_tool("list_referrals", {"company": "itau unibanco"})).structured_content
        said = (await client.call_tool("resolve_form_answer", {"question": "Foi indicado?", "options": ["Sim", "Não"],
                                                               "application_id": app["id"]})).structured_content
        gone = (await client.call_tool("remove_referral", {"id": added["referral"]["id"]})).structured_content
        after = (await client.call_tool("resolve_form_answer", {"question": "Foi indicado?", "options": ["Sim", "Não"],
                                                                "application_id": app["id"]})).structured_content
        failed = await client.call_tool("add_referral", {"company": "Itaú", "name": "Ana", "email": "x"})

    assert added["created"] and listed["count"] == 1 and listed["referrals"][0]["email"] == EMAIL
    assert said["answer"] == "Sim" and said["source"]["kind"] == "indicacao"
    assert gone == {"removed": added["referral"]["id"]}
    assert after["answer"] == "Não"
    assert failed.is_error and "E-mail" in failed.content[0].text


def _conn(db_path):
    from contextlib import closing

    from vagas.db import connect

    return closing(connect(db_path))


def test_the_panel_adds_and_removes_referrals(db_path, skill):
    added = settings_form.referral_action({"action": "add", "referral": {
        "company": "Itaú", "name": "Ana Lima", "email": EMAIL, "phone": "", "scope": "dados"}}, db_path)

    rows = added["referrals"]["rows"]
    assert [(r["company"], r["name"], r["scope"]) for r in rows] == [("Itaú", "Ana Lima", "dados")]
    assert "phone" not in rows[0]
    assert settings_form.load(db_path)["sections"]["referrals"]["rows"] == rows
    with pytest.raises(VagasError, match="name"):
        settings_form.referral_action({"action": "add", "referral": {"company": "Itaú", "name": ""}}, db_path)
    removed = settings_form.referral_action({"action": "remove", "id": rows[0]["id"]}, db_path)
    assert removed["referrals"]["rows"] == []
