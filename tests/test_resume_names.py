"""Nome do PDF do currículo personalizado: empresa, sigla do cargo e ID da candidatura, curto o bastante para os
limites dos sites de vagas (o Bradesco recusa mais de 50 caracteres)."""

import pytest

from vagas.resume_names import MAX_STEM, application_stem, label_stem, role_code


@pytest.mark.parametrize("role, code", [
    ("Data Scientist III", "DS_III"),
    ("Cientista de Dados Sr.", "DS_Sr"),
    ("(Banco de Talentos) - Cientista de Dados Sênior", "DS_Sr"),
    ("Senior ML Engineer - Remote Work", "MLE_Sr"),
    ("Engenheiro de Machine Learning Pleno", "MLE_Pl"),
    ("Engenheiro(a) de Inteligência Artificial (GenAI) Sênior | Híbrido - SP (English Required)", "AIE_Sr"),
    ("Senior AI Engineer | Generative AI & AWS", "AIE_Sr"),
    ("Data Engineer II", "DE_II"),
    ("Analista de Dados Júnior", "DA_Jr"),
    ("Analista de Modelagem II", "AM_II"),
    ("Estágio em Ciência de Dados", "DS_Est"),
    ("Product Manager", "PM"),
])
def test_roles_become_short_codes(role, code):
    assert role_code(role) == code


def test_the_name_has_company_role_code_and_id_without_the_person():
    assert application_stem("Banco Bradesco", "Data Scientist III", 403) == "Banco_Bradesco_DS_III_403"
    assert application_stem("Itaú Unibanco S.A.", "Cientista de Dados Pleno", 7) == "Itau_Unibanco_DS_Pl_7"
    assert application_stem("Serasa Experian", "Analista de Modelagem II", 213) == "Serasa_Experian_AM_II_213"


def test_long_names_are_cut_to_fit_the_strictest_sites():
    stem = application_stem("Companhia Brasileira de Distribuição e Logística Integrada",
                            "Engenheiro(a) de Inteligência Artificial (GenAI) Sênior | Híbrido - SP", 12345)

    assert len(stem) <= MAX_STEM and stem.endswith("_AIE_Sr_12345") and stem.startswith("Companhia")
    assert len(f"{stem}_2.pdf") <= 50  # mesmo com o sufixo de arquivo repetido, cabe no limite do Bradesco


def test_without_an_application_the_name_is_the_label():
    assert label_stem("Geral") == "Curriculo_Geral"
    assert label_stem(None) == "Curriculo"
    assert len(label_stem("Uma descrição muito longa para o currículo de teste genérico")) <= MAX_STEM
