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
