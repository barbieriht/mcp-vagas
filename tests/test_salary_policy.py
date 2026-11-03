from pathlib import Path

import pytest

from vagas.repo import VagasError
from vagas.salary_policy import default_policy_path, load_policy, parse_policy

EXAMPLE = Path(__file__).resolve().parents[1] / "skill" / "candidaturas" / "politica-salarial.example.md"

POLICY = """\
# Política salarial

Faixas mensais em regime CLT.

- Modo: faixa
  - minimo: aplicar se a mediana de mercado for maior ou igual ao mínimo da faixa
  - faixa: aplicar só se a mediana estiver dentro da faixa
- Multiplicador PJ: 1,5
- Remoto nacional (BRL, CLT): mínimo 8.000, máximo 12.000
- Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10.500,50
- Híbrido/presencial em Campinas e região (BRL, CLT): usar a faixa do remoto nacional
- Internacional (USD): mínimo 3400
"""


def test_top_level_settings():
    policy = parse_policy(POLICY)

    assert policy.mode == "faixa"
    assert policy.pj_multiplier == 1.5


@pytest.mark.parametrize("work_mode, location, currency, label, lo, hi", [
    ("remoto", None, "BRL", "Remoto nacional", 8000, 12000),
    ("remoto", "São Paulo, SP", "BRL", "Remoto nacional", 8000, 12000),
    ("hibrido", "Sao Paulo - SP", "BRL", "Híbrido/presencial em São Paulo e região", 10500.5, None),
    ("presencial", "SÃO PAULO", "BRL", "Híbrido/presencial em São Paulo e região", 10500.5, None),
    ("hibrido", "Campinas, São Paulo, Brasil", "BRL", "Híbrido/presencial em Campinas e região", 8000, 12000),
    ("remoto", "Lisboa", "USD", "Internacional", 3400, None),
    ("hibrido", "Lisboa", "USD", "Internacional", 3400, None),
])
def test_band_by_work_mode_location_and_currency(work_mode, location, currency, label, lo, hi):
    band = parse_policy(POLICY).band_for(work_mode, location, currency)

    assert (band.label, band.min, band.max) == (label, lo, hi)


def test_band_tags_regime():
    policy = parse_policy(POLICY)

    assert policy.band_for("remoto", None, "BRL").clt is True
    assert policy.band_for("remoto", None, "USD").clt is False


@pytest.mark.parametrize("work_mode, location, currency, message", [
    ("hibrido", "Curitiba, PR", "BRL", "Curitiba"),
    ("hibrido", None, "BRL", "local"),
    ("remoto", None, "EUR", "EUR"),
])
def test_uncovered_job_is_a_clear_error(work_mode, location, currency, message):
    with pytest.raises(VagasError, match=message):
        parse_policy(POLICY).band_for(work_mode, location, currency)


def test_unknown_work_mode_is_rejected():
    with pytest.raises(VagasError, match="work_mode"):
        parse_policy(POLICY).band_for("teletrabalho", None, "BRL")


@pytest.mark.parametrize("text, message", [
    ("- Modo: minimo\n- Multiplicador PJ: <PREENCHER, ex.: 1.4>\n", r"linha 2.*PREENCHER"),
    ("- Modo: as vezes\n- Remoto (BRL, CLT): mínimo 8000\n", "Modo"),
    ("- Modo: minimo\n- Multiplicador PJ: muito\n- Remoto (BRL, CLT): mínimo 8000\n", "Multiplicador"),
    ("- Modo: minimo\n", "nenhuma faixa"),
    ("- Remoto (BRL, CLT): máximo 9000\n", "mínimo"),
    ("- Remoto (BRL, CLT): mínimo 9000, máximo 8000\n", "máximo"),
    ("- Presencial em Recife (BRL, CLT): usar a faixa do remoto nacional\n", "remoto nacional"),
])
def test_invalid_policy_is_a_clear_error(text, message):
    with pytest.raises(VagasError, match=message):
        parse_policy(text)


def test_mode_defaults_to_minimo_and_multiplier_is_optional():
    policy = parse_policy("- Remoto (BRL, CLT): mínimo 8000\n")

    assert (policy.mode, policy.pj_multiplier) == ("minimo", None)


def test_versioned_example_parses():
    policy = parse_policy(EXAMPLE.read_text(encoding="utf-8"))

    assert policy.band_for("remoto", None, "BRL").min == 8000


def test_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(VagasError, match=r"VAGAS_SALARY_POLICY.*politica-salarial.example.md"):
        load_policy(tmp_path / "politica-salarial.md")


def test_default_path_is_env_or_next_to_db(tmp_path, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_POLICY", raising=False)
    assert default_policy_path(tmp_path / "vagas.db") == tmp_path / "politica-salarial.md"
    monkeypatch.setenv("VAGAS_SALARY_POLICY", str(tmp_path / "x.md"))
    assert default_policy_path(tmp_path / "vagas.db") == tmp_path / "x.md"


def test_values_are_read_the_way_people_write_them():
    policy = parse_policy("- Modo: Mínimo.\n- Multiplicador PJ: 1,4.\n"
                          "- Remoto nacional (brl, clt): mínimo R$ 8.000,00.\n"
                          "- Presencial em São Carlos (BRL, CLT): usar a faixa do remoto nacional.\n")

    assert (policy.mode, policy.pj_multiplier) == ("minimo", 1.4)
    assert policy.band_for("presencial", "São Carlos", "BRL").min == 8000


def test_invalid_mode_lists_the_accepted_values():
    with pytest.raises(VagasError, match=r"as vezes.*minimo.*faixa"):
        parse_policy("- Modo: as vezes\n- Remoto (BRL, CLT): mínimo 8000\n")


def test_example_documents_every_accepted_value():
    from vagas.models import CURRENCIES, SALARY_MODES, WORK_MODES

    text = EXAMPLE.read_text(encoding="utf-8")
    values = text[text.index("## Valores aceitos"):]
    assert all(f"`{v}`" in values for v in (*SALARY_MODES, *CURRENCIES, "CLT"))
    assert all(word in values for word in ("remoto", "híbrido", "presencial"))


CITIES = """\
- Remoto nacional (BRL, CLT): mínimo 8.000
- Híbrido/presencial em São Paulo, Barueri, Campinas, Osasco e Sorocaba (BRL, CLT): mínimo 10.500
- Híbrido/presencial em São Carlos e região (BRL, CLT): mínimo 8.500
"""


@pytest.mark.parametrize("location, minimum", [
    ("Campinas, São Paulo, Brazil", 10500), ("Barueri, SP", 10500), ("São Paulo, São Paulo, Brazil", 10500),
    ("Greater São Paulo Area", 10500), ("Sorocaba", 10500), ("São Carlos, SP, Brasil", 8500),
])
def test_band_lists_several_cities(location, minimum):
    assert parse_policy(CITIES).band_for("hibrido", location, "BRL").min == minimum


def test_state_name_does_not_match_a_city_band():
    with pytest.raises(VagasError, match="Ribeirão Preto"):
        parse_policy(CITIES).band_for("hibrido", "Ribeirão Preto, São Paulo, Brazil", "BRL")
