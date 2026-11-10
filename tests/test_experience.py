"""Anos de experiência: calculados pelo currículo geral, ou o valor que o usuário declara no perfil."""

from datetime import date

from vagas.experience import years_to_declare  # noqa: E402

RESUME = {"experience": [{"start": "Jan 2020", "end": "Jun 2024"}]}  # 4,5 anos


def profile(*fields):
    return {"sections": [{"name": "Respostas padrão", "fields": [
        {"label": label, "value": value, "status": "ok", "notes": notes} for label, value, notes in fields]}]}


def test_without_a_declared_value_the_computed_years_are_rounded_to_the_nearest_year():
    result = years_to_declare(profile(("Anos de experiência a declarar", "calculado", [])), RESUME, date(2026, 1, 1))

    assert result == {"years_exact": 4.5, "years_computed": 5, "years_declared": None, "years_to_inform": 5}


def test_a_declared_number_wins():
    result = years_to_declare(profile(("Anos de experiência a declarar", "6", [])), RESUME, date(2026, 1, 1))

    assert result["years_declared"] == 6 and result["years_to_inform"] == 6 and result["years_computed"] == 5


def test_the_old_sub_item_still_counts_as_the_declared_value():
    old = profile(("Experiência", "períodos do currículo", ["Se o campo pedir anos de experiência: 3"]))

    assert years_to_declare(old, RESUME, date(2026, 1, 1))["years_to_inform"] == 3


def test_without_a_master_resume_nothing_is_computed():
    result = years_to_declare(profile(), None, date(2026, 1, 1))

    assert result == {"years_exact": None, "years_computed": None, "years_declared": None, "years_to_inform": None}
