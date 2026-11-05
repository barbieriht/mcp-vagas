from pathlib import Path

import pytest

from vagas.repo import VagasError
from vagas.triage import default_criteria_path, load_criteria, parse_criteria

EXAMPLE = Path(__file__).resolve().parents[1] / "skill" / "candidaturas" / "criterios-triagem.example.md"

CRITERIA = """\
# Critérios

- Cargos alvo: data_scientist, ml_engineer
- Cargos condicionados à aderência: data_engineer
- Aderência mínima: 60
- Empresas ignoradas: CI&T, Itaú Unibanco S.A.
- Termos de vaga exclusiva PcD: Exclusiva para PcD, vaga afirmativa
- Locais aceitos para híbrido e presencial: São Carlos, São Paulo
"""


def test_lists_are_parsed_and_normalized():
    c = parse_criteria(CRITERIA)

    assert c.target_roles == ("data_scientist", "ml_engineer")
    assert c.conditional_roles == ("data_engineer",)
    assert c.min_match == 60
    assert c.ignored_companies == ("ci&t", "itau unibanco")
    assert c.pcd_terms == ("exclusiva para pcd", "vaga afirmativa")
    assert c.accepted_locations == ("sao carlos", "sao paulo")


def test_versioned_example_parses():
    c = parse_criteria(EXAMPLE.read_text(encoding="utf-8"))

    assert "data_scientist" in c.target_roles and c.min_match == 50


def test_optional_lines_have_safe_defaults():
    c = parse_criteria("- Cargos alvo: data_scientist\n")

    assert (c.conditional_roles, c.min_match, c.ignored_companies, c.pcd_terms, c.accepted_locations) == (
        (), 50, (), (), ())


@pytest.mark.parametrize("text, message", [
    ("- Cargos condicionados à aderência: data_engineer\n", "Cargos alvo"),
    ("- Cargos alvo: data_scientist, astronauta\n", "astronauta"),
    ("- Cargos alvo: data_scientist\n- Aderência mínima: alta\n", "Aderência mínima"),
    ("- Cargos alvo: data_scientist\n- Aderência mínima: 120\n", "Aderência mínima"),
    ("- Cargos alvo: data_scientist\n- Empresas ignoradas: <PREENCHER>\n", r"linha 2.*PREENCHER"),
])
def test_invalid_criteria_are_a_clear_error(text, message):
    with pytest.raises(VagasError, match=message):
        parse_criteria(text)


def test_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(VagasError, match=r"não encontrados.*criterios-triagem.example.md"):
        load_criteria(tmp_path / "criterios-triagem.md")


def test_default_path_is_env_or_next_to_db(tmp_path, monkeypatch):
    monkeypatch.delenv("VAGAS_TRIAGE_CRITERIA", raising=False)
    assert default_criteria_path(tmp_path / "vagas.db") == tmp_path / "criterios-triagem.md"
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(tmp_path / "c.md"))
    assert default_criteria_path(tmp_path / "vagas.db") == tmp_path / "c.md"


def test_search_seniorities_and_location_names():
    c = parse_criteria(CRITERIA + "- Senioridades buscadas: pleno, senior\n")

    assert c.search_seniorities == ("pleno", "senior")
    assert c.location_names == ("São Carlos", "São Paulo")
    with pytest.raises(VagasError, match="mestre"):
        parse_criteria(CRITERIA + "- Senioridades buscadas: mestre\n")


def test_values_are_read_the_way_people_write_them():
    c = parse_criteria(
        "- Cargos alvo: Data Scientist, ML-Engineer, cientista de dados.\n"
        "- Cargos condicionados à aderência: Engenheiro de Dados;\n"
        "- Aderência mínima: 60%.\n"
        "- Empresas ignoradas: CI&T.\n"
        "- Termos de vaga exclusiva PcD: Exclusiva para PcD.\n"
        "- Locais aceitos para híbrido e presencial: São Carlos, São Paulo.\n"
        "- Senioridades buscadas: Pleno, Sênior, Júnior, Estágio.\n"
    )

    assert c.target_roles == ("data_scientist", "ml_engineer")
    assert c.conditional_roles == ("data_engineer",)
    assert c.min_match == 60
    assert c.ignored_companies == ("ci&t",)
    assert c.pcd_terms == ("exclusiva para pcd",)
    assert c.location_names == ("São Carlos", "São Paulo")
    assert c.search_seniorities == ("pleno", "senior", "junior", "estagio")


def test_errors_list_the_accepted_values():
    with pytest.raises(VagasError, match=r"astronauta.*data_scientist.*data_analyst"):
        parse_criteria("- Cargos alvo: astronauta\n")
    with pytest.raises(VagasError, match=r"mestre.*estagio.*especialista"):
        parse_criteria("- Cargos alvo: data_scientist\n- Senioridades buscadas: mestre\n")


def test_example_documents_every_accepted_value():
    from vagas.models import ROLE_KEYS, SENIORITIES

    text = EXAMPLE.read_text(encoding="utf-8")
    values = text[text.index("## Valores aceitos"):]
    assert all(f"`{v}`" in values for v in (*ROLE_KEYS, *SENIORITIES) if v != "outro")
    assert "0 a 100" in values


def test_years_by_level_and_accepted_states():
    c = parse_criteria(CRITERIA + "- Anos por senioridade: júnior 0, Pleno 2, sênior 6.\n"
                       "- Estados aceitos para híbrido e presencial: SP, Minas Gerais\n")

    assert [(lv.name, lv.min, lv.max) for lv in c.years_by_level] == [("junior", 0, None), ("pleno", 2, None),
                                                                     ("senior", 6, None)]
    assert c.accepted_states == ("SP", "MG")


def test_defaults_for_years_and_states():
    c = parse_criteria("- Cargos alvo: data_scientist\n")

    assert [lv.name for lv in c.years_by_level] == ["junior", "pleno", "senior", "especialista", "staff"]
    assert c.accepted_states == ()


@pytest.mark.parametrize("line, message", [
    ("- Anos por senioridade: pleno três\n", "Níveis de experiência"),
    ("- Anos por senioridade: mestre 3\n", "mestre"),
    ("- Estados aceitos para híbrido e presencial: XX\n", "XX"),
])
def test_invalid_years_and_states(line, message):
    with pytest.raises(VagasError, match=message):
        parse_criteria("- Cargos alvo: data_scientist\n" + line)


def test_affirmative_groups_the_user_can_compete_for():
    base = "- Cargos alvo: Data Scientist\n"
    assert parse_criteria(base).affirmative_ok == ()
    assert parse_criteria(base + "- Vagas afirmativas que posso disputar: Mulheres, pessoas negras.\n"
                          ).affirmative_ok == ("women", "black")
    assert parse_criteria(base + "- Vagas afirmativas que posso disputar: nenhuma\n").affirmative_ok == ()
    with pytest.raises(VagasError, match="astronautas"):
        parse_criteria(base + "- Vagas afirmativas que posso disputar: astronautas\n")
