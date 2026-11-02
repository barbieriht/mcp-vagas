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
