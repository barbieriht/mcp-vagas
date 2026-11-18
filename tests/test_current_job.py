"""Empresa, cargo e salário atuais: a experiência em andamento ou, sem nenhuma, o último emprego do currículo geral;
o salário vem de "Valor da última remuneração"."""

from datetime import date

import pytest

from vagas import generic_questions as gq
from vagas.experience import latest_roles, month_label
from vagas.form_answers import resolve
from vagas.pending import unresolved
from vagas.profile_fields import ProfileFiles

TODAY = date(2026, 11, 18)
LAST = [
    {"company": "Acme Analytics", "title": "AI Engineering Technical Coordinator", "start": "May 2024", "end": "Sep 2025"},
    {"company": "Acme Analytics", "title": "Quantitative Analyst", "start": "Feb 2024", "end": "Sep 2025"},
    {"company": "Acme Analytics", "title": "Data Scientist Intern", "start": "Feb 2022", "end": "Feb 2024"},
]
NOW = [{"company": "Beta Dados", "title": "Data Scientist", "start": "Oct 2025", "end": "Present"}, *LAST]

PERFIL = """\
# Dados para formulários

## Respostas padrão
- Valor da última remuneração: R$ 10.500,00 no modelo PJ, com assistência médica e bônus anual
- Informe seu último salário Bruto: R$ 10.500,00 (PJ)

## Outros campos de formulário
- CPF: informar manualmente
"""


@pytest.fixture
def skill(tmp_path):
    (tmp_path / "perfil.md").write_text(PERFIL, encoding="utf-8")
    (tmp_path / "perfil.example.md").write_text(PERFIL, encoding="utf-8")
    return tmp_path


def profile(skill, periods, text=None):
    if text is not None:
        (skill / "perfil.md").write_text(text, encoding="utf-8")
    result = ProfileFiles(skill).get_profile(vault_fields=[])
    result["experience"] = {"periods": periods}
    return result


def test_the_last_roles_are_the_latest_end_with_the_longest_first():
    job = latest_roles(LAST, TODAY)

    assert job["current"] is False and job["end"] == "Sep 2025"
    assert [r["title"] for r in job["roles"]] == ["Quantitative Analyst", "AI Engineering Technical Coordinator"]
    assert latest_roles(NOW, TODAY)["current"] is True
    assert [r["title"] for r in latest_roles(NOW, TODAY)["roles"]] == ["Data Scientist"]
    assert month_label("Sep 2025", TODAY) == "set/2025" and month_label("Sep 2025", TODAY, "en") == "Sep 2025"


@pytest.mark.parametrize("question, kind", [
    ("Empresa atual", gq.COMPANY_NOW), ("Current company", gq.COMPANY_NOW), ("Current employer", gq.COMPANY_NOW),
    ("Em qual empresa você trabalha atualmente?", gq.COMPANY_NOW),
    ("Cargo atual", gq.TITLE_NOW), ("Posição atual", gq.TITLE_NOW), ("Current title", gq.TITLE_NOW),
    ("Current job title", gq.TITLE_NOW), ("Último cargo", gq.TITLE_NOW),
    ("Salário atual", gq.SALARY_NOW), ("Current salary", gq.SALARY_NOW), ("Remuneração atual", gq.SALARY_NOW),
    ("Pretensão salarial", None), ("Cargo pretendido", None),
])
def test_current_job_questions_are_recognized(question, kind):
    assert gq.kind(question) == kind


@pytest.mark.parametrize("question, answer", [
    ("Empresa atual", "Acme Analytics (último emprego, até set/2025)"),
    ("Current company", "Acme Analytics (last job, until Sep 2025)"),
    ("Cargo/Posição atual", "Quantitative Analyst e AI Engineering Technical Coordinator (último emprego, até set/2025)"),
    ("Current title", "Quantitative Analyst and AI Engineering Technical Coordinator (last job, until Sep 2025)"),
    ("Salário atual", "R$ 10.500 mensais (PJ, último emprego, até set/2025)"),
    ("Current salary", "R$ 10,500 per month (PJ, last job, until Sep 2025)"),
])
def test_without_a_current_job_the_free_text_says_it_is_the_last_one(skill, question, answer):
    result = resolve(profile(skill, LAST), question, [], today=TODAY)

    assert result["answer"] == answer and "missing_field" not in result


def test_the_salary_also_comes_as_a_number_and_fits_a_range(skill):
    free = resolve(profile(skill, LAST), "Salário atual", [], today=TODAY)
    ranged = resolve(profile(skill, LAST), "Salário atual", ["Até R$ 5.000", "R$ 5.001 a R$ 10.000",
                                                             "Acima de R$ 10.000"], today=TODAY)

    assert free["number"] == 10500 and free["source"]["field"] == gq.LAST_PAY_LABEL
    assert ranged["answer"] == "Acima de R$ 10.000" and ranged["number"] == 10500


def test_a_list_gets_only_the_value(skill):
    result = resolve(profile(skill, LAST), "Empresa atual", ["Acme Analytics", "Outra"], today=TODAY)

    assert result["answer"] == "Acme Analytics"


def test_a_current_job_is_used_as_is(skill):
    company = resolve(profile(skill, NOW), "Empresa atual", [], today=TODAY)
    title = resolve(profile(skill, NOW), "Current title", [], today=TODAY)

    assert company["answer"] == "Beta Dados" and company["source"]["current"] is True
    assert title["answer"] == "Data Scientist"


def test_an_answered_field_with_the_exact_question_still_wins(skill):
    result = resolve(profile(skill, LAST), "Informe seu último salário Bruto", [], today=TODAY)

    assert result["answer"] == "R$ 10.500,00 (PJ)" and result["source"]["kind"] == "perfil"


def test_without_the_last_pay_it_asks_for_the_generic_field(skill):
    text = PERFIL.replace("- Valor da última remuneração: R$ 10.500,00 no modelo PJ, com assistência médica e bônus anual\n",
                          "- Valor da última remuneração: <PREENCHER>\n")

    result = resolve(profile(skill, LAST, text), "Current salary", [], today=TODAY)

    assert result["missing_field"] == gq.LAST_PAY_LABEL and result["existing"] is True


def test_without_an_approved_resume_it_blocks(skill):
    result = resolve(profile(skill, []), "Cargo atual", [], today=TODAY)

    assert result["blocked"] and "approve_master" in result["reason"] and "missing_field" not in result


def test_an_unanswered_current_salary_field_leaves_with_the_migration(skill):
    text = PERFIL + "- Salário Atual: <PREENCHER>\n- Cargo atual: Analista\n"
    (skill / "perfil.md").write_text(text, encoding="utf-8")

    migration = ProfileFiles(skill).get_profile(vault_fields=[])["migration"]

    assert migration["kind"] == "campos_genericos"
    assert migration["removed"] == [{"label": "Salário Atual", "value": None}]  # o respondido fica


def test_old_pending_items_of_current_job_fields_are_resolved():
    items = [{"kind": "resposta_aberta", "field": "Salário Atual"},
             {"kind": "resposta_aberta", "field": "Empresa atual"}]

    assert unresolved(items, set()) == items[:1]
    assert unresolved(items, {"valor da ultima remuneracao"}) == []


def test_the_salary_does_not_need_the_resume(skill):
    result = resolve(profile(skill, []), "Salário atual", [], today=TODAY)

    assert result["answer"] == "R$ 10.500 mensais (PJ)" and result["number"] == 10500


# --- salário mínimo aceito -------------------------------------------------------------------------

@pytest.mark.parametrize("question", ["Minimum Pay", "Minimum salary", "Pretensão mínima", "Salário mínimo aceitável",
                                      "What is the lowest salary you would accept?"])
def test_minimum_pay_is_recognized(question):
    assert gq.kind(question) == gq.MIN_PAY


def test_minimum_pay_comes_from_the_policy_floor(skill):
    free = resolve(profile(skill, LAST), "Minimum Pay", [], today=TODAY, minimum=11900.0)
    ranged = resolve(profile(skill, LAST), "Pretensão mínima", ["Até R$ 10.000", "Acima de R$ 10.000"], today=TODAY,
                     minimum=11900.0, salary=14000)
    missing = resolve(profile(skill, LAST), "Minimum Pay", [], today=TODAY)

    assert free == {"answer": "11900", "number": 11900,
                    "source": {"kind": "politica_salarial", "field": "mínimo da faixa"}}
    assert ranged["answer"] == "Acima de R$ 10.000"  # o mínimo, não a pretensão
    assert missing["blocked"] and "evaluate_salary" in missing["reason"] and "missing_field" not in missing


@pytest.mark.parametrize("evaluation, floor", [
    ({"floor": 11900.0, "policy": {"my_min": 8500.0}}, 11900.0),
    ({"contract": "clt", "policy": {"my_min": 8500.0, "pj_multiplier": 1.4}}, 8500.0),
    ({"contract": "pj", "policy": {"my_min": 8500.0, "pj_multiplier": 1.4}}, 11900.0),  # avaliação antiga, sem floor
    (None, None),
])
def test_the_floor_comes_from_the_salary_evaluation(evaluation, floor):
    from vagas.server import _floor

    assert _floor(evaluation) == floor
