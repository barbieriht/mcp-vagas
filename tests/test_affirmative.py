import pytest

from vagas.affirmative import GROUPS, detect, parse_groups
from vagas.repo import VagasError


@pytest.mark.parametrize("text, group", [
    ("Vaga exclusiva para mulheres na área de dados.", "women"),
    ("Esta é uma vaga afirmativa para pessoas negras.", "black"),
    ("Processo seletivo destinado a pessoas pretas e pardas", "black"),
    ("Women only: affirmative position for women in tech", "women"),
    ("Vaga para mulheres cientistas de dados", "women"),
    ("Oportunidade exclusiva para pessoas LGBTQIA+", "lgbt"),
    ("Vaga afirmativa para pessoas trans", "lgbt"),
    ("Vaga direcionada a pessoas indígenas", "indigenous"),
    ("Vaga afirmativa para profissionais 50+", "50plus"),
    ("Programa destinado a maiores de 50 anos", "50plus"),
    ("Vaga exclusiva para pessoas com deficiência", "pcd"),
    ("Cientista de Dados | Vaga Afirmativa Mulheres", "women"),
])
def test_affirmative_jobs_are_detected_by_group(text, group):
    assert detect(text).groups == [group]


@pytest.mark.parametrize("text", [
    "Incentivamos candidaturas de mulheres, pessoas negras, LGBTQIA+ e PcD. Somos uma empresa inclusiva.",
    "A vaga não é exclusiva para mulheres; todas as pessoas podem se candidatar.",
    "Buscamos pessoa cientista de dados. Nossa líder é mulher e nosso time é diverso.",
    "Esta vaga é exclusiva para quem mora em São Paulo. Mulheres e homens são bem-vindos.",
    "Black Friday analytics: modelos de previsão de demanda.",
    "Empresa fundada há mais de 50 anos, referência no setor.",
])
def test_inclusive_boilerplate_and_other_uses_are_not_affirmative(text):
    assert detect(text).groups == []


def test_several_groups_and_generic_affirmative_without_a_group():
    assert detect("Vaga afirmativa para mulheres negras").groups == ["women", "black"]
    result = detect("Esta é uma vaga afirmativa.")
    assert result.groups == [] and result.generic is True
    assert detect("Vaga afirmativa para mulheres").generic is False


def test_snippet_shows_where_it_matched():
    assert "exclusiva para mulheres" in detect("Texto. Vaga exclusiva para mulheres. Mais texto.").snippets["women"]


@pytest.mark.parametrize("items, expected", [
    (["Mulheres", "pessoas negras."], ("women", "black")),
    (["negros", "LGBTQIA+", "PcD", "50+", "indígenas"], ("black", "lgbt", "pcd", "50plus", "indigenous")),
    (["mulher", "mulheres"], ("women",)),
    (["nenhuma"], ()),
    ([], ()),
])
def test_user_groups_are_tolerant(items, expected):
    assert parse_groups(items, "criterios.md, linha 3") == expected


def test_unknown_group_lists_the_accepted_values():
    with pytest.raises(VagasError, match=r"linha 3.*astronautas.*mulheres.*pessoas negras"):
        parse_groups(["astronautas"], "criterios.md, linha 3")


def test_groups_have_labels():
    assert set(GROUPS) == {"women", "black", "lgbt", "pcd", "50plus", "indigenous"}


@pytest.mark.parametrize("text, group", [
    ("Esta vaga é exclusiva para pessoas que se identificam com o gênero feminino", "women"),
    ("Vaga destinada ao público feminino", "women"),
    ("Vaga para pessoas do gênero feminino", "women"),
    ("Oportunidade para mulheres na área de dados", "women"),
    ("Esta oportunidade é para mulheres cis e trans", "women"),
    ("Data Scientist - Women only", "women"),
    ("Processo seletivo para pessoas negras", "black"),
    ("Posição para pessoas com deficiência", "pcd"),
])
def test_other_ways_of_saying_the_job_is_for_a_group(text, group):
    assert detect(text).groups == [group]


@pytest.mark.parametrize("text", [
    "Diversidade, todas as nossas vagas são afirmativas: sua singularidade é nosso diferencial",
    "Experian is also proud to be an equal opportunity employer and an affirmative action employer",
    "We are an Equal Opportunity / Affirmative Action employer.",
    "Incentivamos o público feminino a se candidatar.",
])
def test_company_wide_diversity_statements_are_not_an_affirmative_job(text):
    result = detect(text)
    assert result.groups == [] and result.generic is False


def test_weak_markers_need_the_group_right_after():
    assert detect("Vaga para trabalhar com dados num time com muitas mulheres").groups == []
