"""Níveis de experiência: tabela padrão (editável), enquadramento do usuário e efeito na triagem."""

from datetime import date

import pytest

from resume_fixture import fictitious_resume
from test_triage import POLICY, Fetcher, gupy
from vagas.db import connect
from vagas.experience import experience_years
from vagas.job_posting import classify_role
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore
from vagas.triage import Triage, parse_criteria

BASE = "- Cargos alvo: data_scientist, ml_engineer\n- Locais aceitos para híbrido e presencial: São Paulo\n"
LISTED = BASE + "- Senioridades buscadas: junior, pleno, senior\n"


def levels(criteria):
    return [(level.name, level.min, level.max) for level in criteria.years_by_level]


def test_default_levels_follow_the_reference_table():
    assert levels(parse_criteria(BASE)) == [
        ("junior", 0, 2), ("pleno", 2, 5), ("senior", 5, 8), ("especialista", 7, 12), ("staff", 10, 15)]


def test_levels_can_be_edited_with_ranges_or_open_ends():
    text = BASE + "- Níveis de experiência: Júnior 0-2, pleno 2 a 5, Sênior 5–8, especialista 7-12+, staff 10+\n"

    assert levels(parse_criteria(text)) == [
        ("junior", 0, 2), ("pleno", 2, 5), ("senior", 5, 8), ("especialista", 7, 12), ("staff", 10, None)]


def test_old_minimum_only_format_still_works():
    text = BASE + "- Anos por senioridade: júnior 0, Pleno 3, sênior 5\n"

    assert levels(parse_criteria(text)) == [("junior", 0, None), ("pleno", 3, None), ("senior", 5, None)]


@pytest.mark.parametrize("line, message", [
    ("- Níveis de experiência: pleno 5-2\n", "5-2"),
    ("- Níveis de experiência: mestre 3-5\n", "mestre"),
])
def test_invalid_levels_are_a_clear_error(line, message):
    with pytest.raises(VagasError, match=message):
        parse_criteria(BASE + line)


@pytest.mark.parametrize("title, seniority", [
    ("Staff Machine Learning Engineer", "staff"), ("Principal Data Scientist", "staff"),
    ("Especialista em Ciência de Dados", "especialista"), ("Lead Data Scientist", "especialista"),
])
def test_staff_and_principal_titles_are_their_own_level(title, seniority):
    assert classify_role(title)[1] == seniority


def test_experience_merges_overlapping_jobs():
    resume = {"experience": [
        {"start": "Aug 2020", "end": "Sep 2021"}, {"start": "Feb 2022", "end": "Feb 2024"},
        {"start": "Feb 2024", "end": "Sep 2025"}, {"start": "May 2024", "end": "Sep 2025"}]}

    assert experience_years(resume, date(2026, 11, 5)) == 4.8  # 14 + 44 meses


@pytest.mark.parametrize("start, end, years", [
    ("Jan 2025", "Present", 1.0), ("jan 2025", None, 1.0), ("2025-01", "Atual", 1.0), ("fev 2024", "dez 2024", 0.9),
])
def test_experience_dates_in_several_formats(start, end, years):
    resume = {"experience": [{"start": start, "end": end}]}

    assert experience_years(resume, date(2025, 12, 10)) == years


def test_experience_without_readable_dates_is_unknown():
    assert experience_years({"experience": [{"start": "algum dia"}]}, date(2025, 1, 1)) is None


@pytest.fixture
def triage_for(db_path, tmp_path, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    conn = connect(db_path)
    store = ResumeStore(conn, tmp_path / "curriculo.yaml")
    store.save_master_draft(fictitious_resume())  # Feb 2024 a Sep 2025: 1,7 ano, júnior
    store.approve_master()
    (tmp_path / "politica-salarial.md").write_text(POLICY, encoding="utf-8")
    fetcher = Fetcher()

    def make(criteria):
        (tmp_path / "criterios-triagem.md").write_text(criteria, encoding="utf-8")
        return Triage(conn, fetcher=fetcher, criteria_path=tmp_path / "criterios-triagem.md",
                      policy_path=tmp_path / "politica-salarial.md", draft_path=tmp_path / "curriculo.yaml"), fetcher

    yield make
    conn.close()


def test_listed_level_outside_the_users_range_still_goes_ahead(triage_for):
    triage, fetcher = triage_for(LISTED)
    url = fetcher.add(gupy(1, name="Cientista de Dados Pleno"))

    result = triage.triage_job(url)

    assert result["decision"] == "a_aplicar"
    assert result["level"] == {"your_years": 1.7, "your_level": "junior", "job_level": "pleno", "job_years": "2–5",
                               "within": False, "listed": True}
    assert any("fora do seu enquadramento" in r and "pleno" in r for r in result["reasons"])


def test_level_within_the_users_range_is_noted(triage_for):
    triage, fetcher = triage_for(LISTED)
    url = fetcher.add(gupy(2, name="Cientista de Dados Júnior"))

    result = triage.triage_job(url)

    assert result["decision"] == "a_aplicar" and result["level"]["within"] is True
    assert any("dentro do seu enquadramento" in r for r in result["reasons"])


@pytest.mark.parametrize("name", ["Cientista de Dados Especialista", "Staff Data Scientist"])
def test_level_outside_the_list_is_discarded(triage_for, name):
    triage, fetcher = triage_for(LISTED)
    url = fetcher.add(gupy(3, name=name))

    result = triage.triage_job(url)

    assert result["decision"] == "descartada"
    assert "senioridades a que você se candidata" in result["application"]["discard_reason"]


def test_without_a_list_every_level_goes_ahead(triage_for):
    triage, fetcher = triage_for(BASE)
    url = fetcher.add(gupy(4, name="Cientista de Dados Especialista"))

    result = triage.triage_job(url)

    assert result["decision"] == "a_aplicar" and result["level"]["listed"] is True
