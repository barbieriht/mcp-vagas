from pathlib import Path

import pytest

from vagas.repo import VagasError
from vagas.salary_policy import default_policy_path, load_policy, parse_policy

EXAMPLE = Path(__file__).resolve().parents[1] / "skill" / "candidaturas" / "politica-salarial.example.md"

POLICY = """\
# Política salarial

Faixas mensais.

- Modo: faixa
  - minimo: aplicar se a mediana de mercado for maior ou igual ao mínimo da faixa
  - faixa: aplicar só se a mediana estiver dentro da faixa
- Multiplicador PJ: 1,5

- Faixa: mínimo 8.000, máximo 12.000
  - Tipos: remoto
  - Remoto: nacional
  - CLT: sim
- Faixa: mínimo 3400
  - Tipos: remoto
  - Remoto: internacional
  - Moeda: USD
- Faixa: mínimo 9.000
  - Tipos: híbrido, presencial
  - Locais: SP: São Carlos
  - CLT: sim
- Faixa: mínimo 10.500,50
  - Tipos: híbrido
  - Locais: SP: Campinas, Jundiaí
  - CLT: sim
- Faixa: mínimo 11.000
  - Tipos: híbrido, presencial
  - Locais: SP: demais cidades; RJ: Niterói, demais cidades
  - CLT: sim
- Faixa: mínimo 12.000
  - Tipos: presencial
  - Locais: SP: Campinas, Jundiaí
"""


def test_top_level_settings():
    policy = parse_policy(POLICY)

    assert policy.mode == "faixa"
    assert policy.pj_multiplier == 1.5


def test_bands_are_read_with_their_selection():
    bands = parse_policy(POLICY).bands

    assert [(b.label, b.currency, b.clt, b.min, b.max) for b in bands] == [
        ("Remoto nacional", "BRL", True, 8000, 12000),
        ("Remoto internacional", "USD", False, 3400, None),
        ("Híbrido/presencial em São Carlos", "BRL", True, 9000, None),
        ("Híbrido em Campinas, Jundiaí", "BRL", True, 10500.5, None),
        ("Híbrido/presencial em demais cidades de SP, Niterói, demais cidades de RJ", "BRL", True, 11000, None),
        ("Presencial em Campinas, Jundiaí", "BRL", False, 12000, None),
    ]
    assert bands[4].rest == ("SP", "RJ") and bands[4].places[1].cities == ("Niterói",)


@pytest.mark.parametrize("work_mode, location, currency, minimum", [
    ("remoto", None, "BRL", 8000),
    ("remoto", "São Paulo, SP", "BRL", 8000),
    ("remoto", "Lisboa, Portugal", "USD", 3400),  # internacional pela moeda
    ("hibrido", "São Carlos, SP, Brasil", "BRL", 9000),
    ("presencial", "SÃO CARLOS", "BRL", 9000),  # sem estado: vale a cidade
    ("hibrido", "Jundiaí, São Paulo, Brazil", "BRL", 10500.5),
    ("presencial", "Jundiaí, SP", "BRL", 12000),  # mesma cidade, outra modalidade, outro valor
    ("hibrido", "Ribeirão Preto, São Paulo, Brazil", "BRL", 11000),  # demais cidades de SP
    ("hibrido", "Greater São Paulo Area", "BRL", 11000),
    ("presencial", "Niterói, RJ", "BRL", 11000),
    ("hibrido", "Petrópolis, Rio de Janeiro, Brasil", "BRL", 11000),
])
def test_band_by_work_mode_location_and_currency(work_mode, location, currency, minimum):
    assert parse_policy(POLICY).band_for(work_mode, location, currency).min == minimum


@pytest.mark.parametrize("work_mode, location, currency, message", [
    ("hibrido", "Curitiba, PR", "BRL", "Curitiba"),
    ("hibrido", "São Carlos, SC", "BRL", "São Carlos, SC"),  # outro São Carlos
    ("hibrido", None, "BRL", "local"),
    ("remoto", None, "EUR", "internacional.*EUR"),
    ("hibrido", "São Carlos, SP", "USD", "USD"),
])
def test_uncovered_job_is_a_clear_error(work_mode, location, currency, message):
    with pytest.raises(VagasError, match=message):
        parse_policy(POLICY).band_for(work_mode, location, currency)


def test_unknown_work_mode_is_rejected():
    with pytest.raises(VagasError, match="work_mode"):
        parse_policy(POLICY).band_for("teletrabalho", None, "BRL")


REMOTE = "- Faixa: mínimo 8000\n  - Tipos: remoto\n  - Remoto: nacional\n"


@pytest.mark.parametrize("text, message", [
    ("- Modo: minimo\n- Multiplicador PJ: <PREENCHER, ex.: 1.4>\n" + REMOTE, r"linha 2.*PREENCHER"),
    ("- Modo: as vezes\n" + REMOTE, "Modo"),
    ("- Multiplicador PJ: muito\n" + REMOTE, "Multiplicador"),
    ("- Modo: minimo\n", "nenhuma faixa"),
    ("- Faixa: máximo 9000\n  - Tipos: remoto\n  - Remoto: nacional\n", "mínimo"),
    ("- Faixa: mínimo 9000, máximo 8000\n  - Tipos: remoto\n  - Remoto: nacional\n", "máximo"),
    ("- Faixa: mínimo 9000\n", r"linha 1.*Tipos"),
    ("- Faixa: mínimo 9000\n  - Tipos: teletrabalho\n", "teletrabalho"),
    ("- Faixa: mínimo 9000\n  - Tipos: remoto\n", "Remoto"),
    ("- Faixa: mínimo 9000\n  - Tipos: remoto\n  - Remoto: nacional, internacional\n", "moeda"),
    ("- Faixa: mínimo 9000\n  - Tipos: remoto\n  - Remoto: internacional\n", "Moeda"),
    ("- Faixa: mínimo 9000\n  - Tipos: remoto\n  - Remoto: internacional\n  - Moeda: BRL\n", "USD"),
    ("- Faixa: mínimo 9000\n  - Tipos: remoto, híbrido\n  - Remoto: internacional\n  - Moeda: USD\n"
     "  - Locais: SP: Barueri\n", "internacional"),
    ("- Faixa: mínimo 9000\n  - Tipos: híbrido\n", "Locais"),
    ("- Faixa: mínimo 9000\n  - Tipos: híbrido\n  - Locais: Narnia: Cair Paravel\n", "Narnia"),
    ("- Faixa: mínimo 9000\n  - Tipos: híbrido\n  - Locais: demais cidades\n", "demais cidades"),
    ("- Faixa: mínimo 9000\n  - Tipos: híbrido\n  - Locais: SP: Barueri\n"
     "- Faixa: mínimo 9500\n  - Tipos: híbrido, presencial\n  - Locais: SP: Osasco, Barueri\n", r"Barueri.*linha 1"),
    (REMOTE + REMOTE.replace("8000", "9000"), r"remoto nacional.*linha 1"),
    ("- Remoto nacional (BRL, CLT): mínimo 8000\n", "formato antigo"),
])
def test_invalid_policy_is_a_clear_error(text, message):
    with pytest.raises(VagasError, match=message):
        parse_policy(text)


def test_same_city_in_two_work_modes_can_share_or_split_values():
    policy = parse_policy("- Faixa: mínimo 9000\n  - Tipos: híbrido\n  - Locais: SP: Barueri\n"
                          "- Faixa: mínimo 9500\n  - Tipos: presencial\n  - Locais: SP: Barueri, demais cidades\n")

    assert policy.band_for("hibrido", "Barueri, SP", "BRL").min == 9000
    assert policy.band_for("presencial", "Barueri, SP", "BRL").min == 9500


def test_mode_defaults_to_minimo_and_multiplier_is_optional():
    policy = parse_policy(REMOTE)

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
                          "- Faixa: mínimo R$ 8.000,00.\n  - Tipos: Remoto, Híbrido.\n  - Remoto: Nacional.\n"
                          "  - Locais: sp: São Carlos.\n  - CLT: Sim.\n")

    assert (policy.mode, policy.pj_multiplier) == ("minimo", 1.4)
    assert policy.band_for("hibrido", "São Carlos", "BRL").min == 8000
    assert policy.band_for("remoto", None, "BRL").clt is True


def test_invalid_mode_lists_the_accepted_values():
    with pytest.raises(VagasError, match=r"as vezes.*minimo.*faixa"):
        parse_policy("- Modo: as vezes\n" + REMOTE)


def test_example_documents_every_accepted_value():
    from vagas.models import CURRENCIES, SALARY_MODES

    text = EXAMPLE.read_text(encoding="utf-8")
    values = text[text.index("## Valores aceitos"):]
    assert all(f"`{v}`" in values for v in (*SALARY_MODES, *CURRENCIES, "remoto", "híbrido", "presencial",
                                             "nacional", "internacional", "demais cidades"))
