"""Perguntas que repetem o nome de cada empresa ("Você trabalha na empresa X?", "Foi indicado?"): respondidas pelo
currículo geral e por campos genéricos do perfil, sem criar um campo por empresa."""

from datetime import date

import pytest
from mcp import Client

from test_sensitive import FakeBackend
from vagas import generic_questions as gq
from vagas.form_answers import resolve
from vagas.pending import unresolved
from vagas.profile_fields import ProfileFiles
from vagas.sensitive import Vault
from vagas.server import build_server

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 18)

PERFIL = """\
# Dados para formulários

## Respostas padrão
- Parentes na empresa: não
- Trabalha atualmente na empresa da vaga: pelo currículo geral
- Já trabalhou na empresa da vaga: pelo currículo geral
- Foi indicado por alguém da empresa: Não
- Você já foi empregado(a) do Banco Exemplo S.A.? (opções Sim, atuei como estagiário(a), Não atuei): Sim, atuei como estagiário(a)

## Outros campos de formulário
- CPF: informar manualmente
"""

PAST = [{"company": "Acme Analytics Ltda.", "title": "Quantitative Analyst", "start": "Feb 2024", "end": "Sep 2025"}]
NOW = [{"company": "Beta Dados S.A.", "title": "Data Scientist", "start": "Oct 2025", "end": "Present"}, *PAST]


@pytest.fixture
def skill(tmp_path, monkeypatch):
    folder = tmp_path / "skill"
    folder.mkdir()
    (folder / "perfil.md").write_text(PERFIL, encoding="utf-8")
    (folder / "perfil.example.md").write_text(PERFIL, encoding="utf-8")
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(folder))
    return folder


def profile(skill, periods):
    result = ProfileFiles(skill).get_profile(vault_fields=[])
    result["experience"] = {"periods": periods}
    return result


# --- reconhecimento --------------------------------------------------------------------------------

@pytest.mark.parametrize("question, kind", [
    ("Você trabalha na empresa Vibra Energia?", gq.CURRENT),
    ("É colaborador Luza Group?", gq.CURRENT),
    ("Você é funcionário(a) do Itaú?", gq.CURRENT),
    ("Você trabalha atualmente nesta empresa?", gq.CURRENT),
    ("Are you a current employee of Nubank?", gq.CURRENT),
    ("Do you currently work for Acme?", gq.CURRENT),
    ("Have you previously worked at Nubank or any company acquired by Nubank?", gq.PAST),
    ("Você já trabalhou na Ambev?", gq.PAST),
    ("Você já foi colaborador do Grupo Boticário?", gq.PAST),
    ("É ex-funcionário da empresa?", gq.PAST),
    ("Alguém que trabalha nesta empresa indicou você para esta vaga?", gq.REFERRAL),
    ("Foi indicado?", gq.REFERRAL),
    ("Were you referred by a current employee?", gq.REFERRAL),
    ("Nome do colaborador que indicou", gq.REFERRAL),
    ("Você trabalha na área de dados?", None),  # sem empresa à vista
    ("Algum parente seu trabalha na empresa?", None),  # outra pessoa
    ("Have you participated in a hiring process with Nubank in the last 6 months?", None),
    ("Como ficou sabendo de nossas oportunidades?", None),
    ("Are you legally authorized to work in the country where this position is located?", None),
])
def test_questions_are_recognized_by_pattern(question, kind):
    assert gq.kind(question) == kind


def test_the_application_company_counts_as_a_company_in_sight():
    assert gq.kind("Você trabalha na Vibra?", company="Vibra Energia S.A.") == gq.CURRENT


@pytest.mark.parametrize("a, b, same", [
    ("Acme Analytics Ltda.", "ACME ANALYTICS S.A.", True),
    ("Itaú", "Itaú Unibanco S.A.", True),
    ("Grupo Boticário", "Boticário", True),
    ("Grupo Boticário", "Grupo Pão de Açúcar", False),  # só a palavra genérica em comum
    ("Banco Exemplo", "Banco", False),
])
def test_companies_are_compared_normalized_by_whole_words(a, b, same):
    assert gq.same_company(a, b) is same


# --- respostas -------------------------------------------------------------------------------------

@pytest.mark.parametrize("question, options, company, periods, answer", [
    ("Você trabalha na empresa Vibra Energia?", ["Sim", "Não"], "Vibra Energia", NOW, "Não"),
    ("É colaborador Luza Group?", ["Sim", "Não"], None, PAST, "Não"),
    ("Você trabalha atualmente nesta empresa?", ["Sim", "Não"], "Beta Dados", NOW, "Sim"),
    ("Você trabalha atualmente nesta empresa?", ["Sim", "Não"], "Acme Analytics", NOW, "Não"),  # já saiu
    ("Are you a current employee of Beta Dados?", ["Yes", "No"], None, NOW, "Yes"),
    ("Have you previously worked at Acme?", ["Yes", "No"], "ACME ANALYTICS S.A.", PAST, "Yes"),
    ("Have you previously worked at Nubank or any company acquired by Nubank?", ["Yes", "No"], "Nubank", PAST, "No"),
    ("Você já trabalhou nesta empresa?", [], "Acme Analytics", PAST, "Sim"),
    ("Have you ever worked for this company?", [], "Nubank", PAST, "No"),
])
def test_working_there_comes_from_the_master_resume(skill, question, options, company, periods, answer):
    result = resolve(profile(skill, periods), question, options, company=company, today=TODAY)

    assert result["answer"] == answer and "missing_field" not in result
    assert result["source"]["kind"] == "curriculo"


def test_no_field_is_created_with_the_company_name(skill):
    result = resolve(profile(skill, PAST), "Você trabalha na empresa Vibra Energia?", ["Sim", "Não"], today=TODAY)

    assert result["answer"] == "Não"
    assert "Vibra" not in (skill / "perfil.md").read_text(encoding="utf-8")


def test_this_company_without_the_application_asks_for_it(skill):
    result = resolve(profile(skill, PAST), "Você trabalha nesta empresa?", ["Sim", "Não"], today=TODAY)

    assert result["blocked"] and "application_id" in result["reason"]


def test_without_an_approved_resume_it_blocks(skill):
    result = resolve(profile(skill, []), "Você já trabalhou na Ambev?", ["Sim", "Não"], company="Ambev", today=TODAY)

    assert result["blocked"] and "approve_master" in result["reason"] and "missing_field" not in result


def test_an_answered_field_with_the_exact_question_still_wins(skill):
    result = resolve(profile(skill, PAST), "Você já foi empregado(a) do Banco Exemplo S.A.?",
                     ["Sim, atuei como estagiário(a)", "Não atuei"], company="Banco Exemplo", today=TODAY)

    assert result["answer"] == "Sim, atuei como estagiário(a)" and result["source"]["kind"] == "perfil"


@pytest.mark.parametrize("question, options, answer", [
    ("Foi indicado?", ["Não", "Sim"], "Não"),
    ("Alguém que trabalha nesta empresa indicou você para esta vaga?", ["Sim", "Não"], "Não"),
    ("Were you referred by a current employee?", ["Yes", "No"], "No"),
    ("Were you referred?", [], "No"),
])
def test_referral_uses_the_generic_field_for_every_company(skill, question, options, answer):
    result = resolve(profile(skill, PAST), question, options, company="Qualquer Uma", today=TODAY)

    assert result == {"answer": answer, "source": {"kind": "perfil", "field": gq.REFERRAL_LABEL,
                                                   "section": "Respostas padrão"}}


def test_a_referrer_name_with_no_referral_is_left_blank(skill):
    result = resolve(profile(skill, PAST), "Nome do colaborador que indicou você", [], today=TODAY)

    assert result["blocked"] and "em branco" in result["reason"] and "missing_field" not in result


def test_without_the_referral_field_the_generic_one_is_asked(skill):
    text = PERFIL.replace("- Foi indicado por alguém da empresa: Não\n", "")
    (skill / "perfil.md").write_text(text, encoding="utf-8")

    result = resolve(profile(skill, PAST), "É colaborador indicado por alguém da Luza Group?", ["Sim", "Não"])

    assert result["missing_field"] == gq.REFERRAL_LABEL and result["section"] == "Respostas padrão"
    assert result["existing"] is False


def test_the_generic_labels_never_answer_other_questions_by_similarity(skill):
    result = resolve(profile(skill, PAST), "Você trabalha atualmente?", ["Sim", "Não"], today=TODAY)

    assert result.get("missing_field")  # situação de emprego, não a empresa da vaga


# --- migração dos campos por empresa ---------------------------------------------------------------

OLD = """\
# Dados para formulários

## Respostas padrão
- Parentes na empresa: não

## Outros campos de formulário
- Alguém que trabalha nesta empresa indicou você para esta vaga? (opções Sim, Não): <PREENCHER>
- Você trabalha na empresa Vibra Energia? (opções Sim, Não): Não
- É colaborador Luza Group? (opções Sim, Não): Não
- Foi indicado? (opções Não, Sim): Não
- Have you previously worked at Nubank or any company acquired by Nubank? (opções Yes, No): <PREENCHER>
- Você já trabalhou na Ambev? (opções Sim, Não): Sim
- Possui participação societária em alguma empresa? (opções Sim, Não): Não
"""


def test_company_fields_become_a_proposal(skill):
    (skill / "perfil.md").write_text(OLD, encoding="utf-8")

    migration = ProfileFiles(skill).get_profile(vault_fields=[])["migration"]

    assert migration["kind"] == "campos_genericos"
    assert [r["label"].split("?")[0] for r in migration["removed"]] == [
        "Alguém que trabalha nesta empresa indicou você para esta vaga", "Você trabalha na empresa Vibra Energia",
        "É colaborador Luza Group", "Foi indicado", "Have you previously worked at Nubank or any company acquired by Nubank"]
    assert {f["label"]: f["value"] for f in migration["fields"]} == {
        gq.CURRENT_LABEL: gq.FROM_RESUME, gq.PAST_LABEL: gq.FROM_RESUME, gq.REFERRAL_LABEL: "Não"}


def test_applying_it_drops_the_company_fields_and_keeps_a_yes(skill):
    (skill / "perfil.md").write_text(OLD, encoding="utf-8")
    (skill / "perfil.example.md").write_text(OLD.replace(": Não\n", ": <...>\n"), encoding="utf-8")

    result = ProfileFiles(skill).apply_migration()

    text = (skill / "perfil.md").read_text(encoding="utf-8")
    assert result["kind"] == "campos_genericos" and len(result["removed"]) == 5
    labels = [line for line in text.splitlines() if line.startswith("- ")]
    for gone in ("Vibra", "Luza", "Nubank", "Foi indicado?", "Alguém que trabalha"):
        assert not any(gone in line for line in labels)
    assert "- Você já trabalhou na Ambev? (opções Sim, Não): Sim" in text  # pode não estar no currículo
    assert "- Possui participação societária" in text
    assert (f"- {gq.CURRENT_LABEL}: {gq.FROM_RESUME}\n  - {gq.NOTES[gq.CURRENT]}\n"
            f"- {gq.PAST_LABEL}: {gq.FROM_RESUME}\n  - {gq.NOTES[gq.PAST]}\n"
            f"- {gq.REFERRAL_LABEL}: Não\n  - {gq.NOTES[gq.REFERRAL]}\n") in text
    example = (skill / "perfil.example.md").read_text(encoding="utf-8")
    assert "Vibra" not in example and f"- {gq.REFERRAL_LABEL}: <...>" in example
    assert "migration" not in ProfileFiles(skill).get_profile(vault_fields=[])


def test_old_pending_items_of_company_fields_are_resolved():
    items = [{"kind": "resposta_aberta", "field": "Você trabalha na empresa Vibra Energia? (opções Sim, Não)"},
             {"kind": "resposta_aberta", "field": "Foi indicado? (opções Não, Sim)"},
             {"kind": "resposta_aberta", "field": "Qual o seu tamanho de camiseta?"}]

    assert unresolved(items, set()) == items[1:]
    assert unresolved(items, {"foi indicado por alguem da empresa"}) == items[2:]


# --- pelo MCP --------------------------------------------------------------------------------------

async def test_the_application_company_reaches_the_answer(skill, db_path):
    from resume_fixture import fictitious_resume
    from vagas.db import connect
    from vagas.repo import Repo
    from vagas.resume_repo import ResumeStore, default_draft_path

    with connect(db_path) as conn:
        store = ResumeStore(conn, default_draft_path(db_path))
        store.save_master_draft(fictitious_resume())
        store.approve_master()
        app = Repo(conn).add_application("ACME ANALYTICS S.A.", "Data Scientist", "gupy", status="a_aplicar")["application"]
    async with Client(build_server(db_path, vault=Vault(skill / "cofre.json", FakeBackend()))) as client:
        result = (await client.call_tool("resolve_form_answer", {
            "question": "Você já trabalhou nesta empresa?", "options": ["Sim", "Não"],
            "application_id": app["id"]})).structured_content

    assert result["answer"] == "Sim" and result["source"]["kind"] == "curriculo"
