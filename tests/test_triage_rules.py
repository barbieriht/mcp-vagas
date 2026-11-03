import pytest

from vagas.triage import parse_criteria, state_of, years_required


@pytest.mark.parametrize("text, years", [
    ("What we are looking for: 4+ years of experience in ML.", 4),
    ("Experiência mínima de 5 anos com Python.", 5),
    ("Buscamos 3 a 5 anos de experiência em ciência de dados.", 3),
    ("At least 2 years of professional experience.", 2),
    ("Experience: 6+ years building models.", 6),
    ("We have been leading technology projects for over 15 years. 3+ years of experience required.", 3),
    ("Somos uma empresa com mais de 70 anos de existência.", None),
    ("For over 50 years, organizations have trusted us to deliver great customer experiences.", None),
    ("Sem requisito de tempo.", None),
])
def test_years_required(text, years):
    assert years_required(text) == years


@pytest.mark.parametrize("location, state", [
    ("São Paulo, SP, Brasil", "SP"), ("Barueri, São Paulo, Brazil", "SP"), ("Greater São Paulo Area", "SP"),
    ("Florianópolis, Santa Catarina, Brazil", "SC"), ("Fortaleza, Ceará, Brazil", "CE"),
    ("Belo Horizonte, MG", "MG"), ("Rio de Janeiro, Rio de Janeiro, Brasil", "RJ"), ("Brazil", None), (None, None),
    ("Lisboa, Portugal", None),
])
def test_state_of(location, state):
    assert state_of(location) == state
