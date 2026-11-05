import pytest
from mcp import Client

from test_sensitive import FakeBackend
from vagas.profile_fields import ProfileFiles
from vagas.repo import VagasError
from vagas.sensitive import Vault
from vagas.server import build_server

pytestmark = pytest.mark.anyio

PERFIL = """\
# Dados para formulários

Fonte da verdade: o currículo geral.

## Contato e identificação
- Nome: Thiago Teste
- E-mail / login Google: thiago@example.com

## Respostas padrão
- Idiomas: português (nativo), inglês B2
  - Em escala fixa, escolher a opção mais próxima de B2.
- Anos de experiência: <PREENCHER: quantos anos declarar>

## Outros campos de formulário
Campos pedidos por formulários.
- CPF: no cofre (get_sensitive_field)
- RG: no cofre (get_sensitive_field)
- Senha do portal: informar manualmente
"""


@pytest.fixture
def skill(tmp_path):
    (tmp_path / "perfil.md").write_text(PERFIL, encoding="utf-8")
    (tmp_path / "perfil.example.md").write_text(PERFIL, encoding="utf-8")
    return tmp_path


def test_profile_is_structured_with_status(skill):
    profile = ProfileFiles(skill).get_profile(vault_fields=["cpf"])

    assert [s["name"] for s in profile["sections"]] == [
        "Contato e identificação", "Respostas padrão", "Outros campos de formulário"]
    contact = profile["sections"][0]["fields"]
    assert contact[1] == {"label": "E-mail / login Google", "value": "thiago@example.com", "status": "ok", "notes": []}
    languages = profile["sections"][1]["fields"][0]
    assert languages["notes"] == ["Em escala fixa, escolher a opção mais próxima de B2."]
    other = {f["label"]: f for f in profile["sections"][2]["fields"]}
    assert other["CPF"]["status"] == "cofre" and other["CPF"]["vault_field"] == "cpf"
    assert other["RG"]["status"] == "cofre_vazio"
    assert other["Senha do portal"]["status"] == "manual"
    assert profile["to_fill"] == ["Anos de experiência"]
    assert profile["vault_missing"] == ["RG"]


def test_missing_profile_is_a_clear_error(tmp_path):
    with pytest.raises(VagasError, match="perfil.md"):
        ProfileFiles(tmp_path).get_profile(vault_fields=[])


async def test_get_profile_via_mcp(db_path, skill, tmp_path, monkeypatch):
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(skill))
    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    vault.set("cpf", "529.982.247-25")
    async with Client(build_server(db_path, vault=vault)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        profile = (await client.call_tool("get_profile", {})).structured_content

    other = {f["label"]: f for f in profile["sections"][2]["fields"]}
    assert other["CPF"]["status"] == "cofre"
    assert "52998224725" not in str(profile)
    assert "get_sensitive_field" in tools["get_profile"].description


@pytest.mark.parametrize("marker", ["cofre (get_sensitive_field)", "Cofre", "no cofre.", "No cofre (get_sensitive_field)"])
def test_vault_marker_is_read_tolerantly(tmp_path, marker):
    (tmp_path / "perfil.md").write_text(f"## Outros\n- RG: {marker}\n", encoding="utf-8")

    field = ProfileFiles(tmp_path).get_profile(vault_fields=["rg"])["sections"][0]["fields"][0]

    assert (field["status"], field["vault_field"]) == ("cofre", "rg")


def test_a_document_stored_in_the_vault_wins_over_a_stale_manual_marker(tmp_path):
    (tmp_path / "perfil.md").write_text("## Outros\n- CPF: informar manualmente\n- RG: informar manualmente\n",
                                        encoding="utf-8")

    fields = {f["label"]: f for f in ProfileFiles(tmp_path).get_profile(vault_fields=["cpf"])["sections"][0]["fields"]}

    assert fields["CPF"]["status"] == "cofre" and fields["CPF"]["vault_field"] == "cpf"
    assert fields["RG"]["status"] == "manual"


def test_birth_date_is_an_ordinary_profile_field(tmp_path):
    (tmp_path / "perfil.md").write_text("## Contato\n- Data de nascimento: <PREENCHER: DD/MM/AAAA>\n", encoding="utf-8")

    profile = ProfileFiles(tmp_path).get_profile(vault_fields=[])

    assert profile["to_fill"] == ["Data de nascimento"]


def test_example_profile_asks_for_the_birth_date():
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "skill" / "candidaturas" / "perfil.example.md"
    assert "- Data de nascimento:" in example.read_text(encoding="utf-8")
