import pytest
from mcp import Client

from vagas.profile_fields import ProfileFiles, default_skill_dir
from vagas.repo import VagasError
from vagas.server import build_server

pytestmark = pytest.mark.anyio

PERFIL = """\
# Dados para formulários

## Contato e identificação
- Nome: Thiago Teste
- Telefone: +55 (00) 0000-0000

## Respostas padrão
- Idiomas: português (nativo)
  - Escala fixa: escolher a mais próxima.
- Parentes na empresa: não

## Outros campos de formulário
Campos pedidos por formulários que não se encaixam nas seções acima.
- Pretensão de início: imediato
"""
EXAMPLE = PERFIL.replace("Thiago Teste", "Fulano de Tal").replace("- Pretensão de início: imediato",
                                                                   "- <Rótulo do campo como o formulário pede>: <...>")


@pytest.fixture
def skill(tmp_path):
    (tmp_path / "perfil.md").write_text(PERFIL, encoding="utf-8")
    (tmp_path / "perfil.example.md").write_text(EXAMPLE, encoding="utf-8")
    return tmp_path


def read(skill, name):
    return (skill / name).read_text(encoding="utf-8")


def test_field_goes_to_other_fields_in_both_files(skill):
    result = ProfileFiles(skill).add_profile_field("Disponibilidade para viagens")

    assert result["created"] == {"perfil": True, "example": True}
    assert result["section"] == "Outros campos de formulário"
    assert read(skill, "perfil.md").endswith("- Pretensão de início: imediato\n- Disponibilidade para viagens: <PREENCHER>\n")
    assert read(skill, "perfil.example.md").endswith(
        "- <Rótulo do campo como o formulário pede>: <...>\n- Disponibilidade para viagens: <...>\n")


def test_value_and_existing_section_after_sub_items(skill):
    ProfileFiles(skill).add_profile_field("LinkedIn", section="contato", value="https://linkedin.com/in/x")
    ProfileFiles(skill).add_profile_field("Cargo público", section="Respostas Padrao", value="nunca ocupou")

    perfil = read(skill, "perfil.md")
    assert "- Telefone: +55 (00) 0000-0000\n- LinkedIn: https://linkedin.com/in/x\n\n## Respostas" in perfil
    assert "- Parentes na empresa: não\n- Cargo público: nunca ocupou\n\n## Outros" in perfil
    assert "- LinkedIn: <...>" in read(skill, "perfil.example.md")


def test_duplicate_is_not_recreated_but_placeholder_gets_the_answer(skill):
    files = ProfileFiles(skill)
    files.add_profile_field("Disponibilidade para viagens")

    again = files.add_profile_field("disponibilidade  para VIAGENS")
    answered = files.add_profile_field("Disponibilidade para viagens", value="sim, eventuais")
    kept = files.add_profile_field("Parentes na empresa", value="sim")

    assert again["created"] == {"perfil": False, "example": False} and again["updated"] is False
    assert answered["updated"] is True
    assert "- Disponibilidade para viagens: sim, eventuais\n" in read(skill, "perfil.md")
    assert read(skill, "perfil.md").count("Disponibilidade para viagens") == 1
    assert kept["updated"] is False and "- Parentes na empresa: não" in read(skill, "perfil.md")


@pytest.mark.parametrize("label, sensitive", [("CPF", False), ("Número do RG", False), ("Matrícula", True)])
def test_sensitive_fields_refuse_values_and_store_manual(skill, label, sensitive):
    files = ProfileFiles(skill)
    with pytest.raises(VagasError, match="sensível"):
        files.add_profile_field(label, value="123", sensitive=sensitive)

    files.add_profile_field(label, sensitive=sensitive)

    assert f"- {label}: informar manualmente\n" in read(skill, "perfil.md")
    assert f"- {label}: informar manualmente\n" in read(skill, "perfil.example.md")


def test_unknown_section_lists_the_existing_ones(skill):
    with pytest.raises(VagasError, match="Contato e identificação.*Respostas padrão"):
        ProfileFiles(skill).add_profile_field("X", section="Financeiro")


def test_missing_other_section_is_created(skill):
    (skill / "perfil.md").write_text("# Dados\n\n## Contato e identificação\n- Nome: X\n", encoding="utf-8")

    ProfileFiles(skill).add_profile_field("Hobby", value="xadrez")

    assert read(skill, "perfil.md").endswith("- Nome: X\n\n## Outros campos de formulário\n- Hobby: xadrez\n")


def test_missing_files_are_a_clear_error(tmp_path):
    with pytest.raises(VagasError, match="perfil.md"):
        ProfileFiles(tmp_path).add_profile_field("X")


def test_skill_dir_from_env_or_policy_symlink(tmp_path, monkeypatch, skill):
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(skill))
    assert default_skill_dir(tmp_path / "db" / "vagas.db") == skill

    monkeypatch.delenv("VAGAS_SKILL_DIR")
    monkeypatch.delenv("VAGAS_SALARY_POLICY", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    (skill / "politica-salarial.md").write_text("- Modo: minimo\n", encoding="utf-8")
    (data / "politica-salarial.md").symlink_to(skill / "politica-salarial.md")
    assert default_skill_dir(data / "vagas.db") == skill

    with pytest.raises(VagasError, match="VAGAS_SKILL_DIR"):
        default_skill_dir(tmp_path / "vazio" / "vagas.db")


async def test_add_profile_field_via_mcp(db_path, skill, monkeypatch):
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(skill))
    async with Client(build_server(db_path)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        ok = (await client.call_tool("add_profile_field", {"label": "Hobby", "value": "xadrez"})).structured_content
        bad = await client.call_tool("add_profile_field", {"label": "Senha do portal", "value": "x"})

    assert ok["created"]["perfil"] is True
    assert bad.is_error and "sensível" in bad.content[0].text
    assert "informar manualmente" in tools["add_profile_field"].description
