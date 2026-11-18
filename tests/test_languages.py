"""Idiomas no perfil: o nível declarado fica em "Idiomas" e o certificado em "Certificações de idiomas"; a linha
antiga, que juntava os dois, vira uma proposta de migração que o usuário confirma."""

import json

import pytest
from mcp import Client

from test_sensitive import FakeBackend
from vagas import languages
from vagas.db import connect
from vagas.profile_fields import ProfileFiles
from vagas.repo import Repo
from vagas.sensitive import Vault
from vagas.server import build_server

pytestmark = pytest.mark.anyio

OLD = """\
# Dados para formulários

## Respostas padrão
- Idiomas: português (nativo), inglês avançado (B2, certificado), espanhol intermediário (A2.3, certificado)
  - Em formulários com escala fixa, escolher a opção mais próxima de B2 / A2 sem arredondar para cima.
  - Libras: só leitura.
- Parentes na empresa: não

## Outros campos de formulário
- CPF: informar manualmente
"""

EXAMPLE = """\
# Dados para formulários

## Respostas padrão
- Idiomas: português (nativo), inglês (avançado)
- Parentes na empresa: não
"""


@pytest.fixture
def skill(tmp_path, monkeypatch):
    folder = tmp_path / "skill"
    folder.mkdir()
    (folder / "perfil.md").write_text(OLD, encoding="utf-8")
    (folder / "perfil.example.md").write_text(EXAMPLE, encoding="utf-8")
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(folder))
    return folder


def profile(skill):
    return ProfileFiles(skill).get_profile(vault_fields=[])


# --- separação -------------------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("português (nativo), inglês avançado (B2, certificado), espanhol intermediário (A2.3, certificado)",
     ("português (nativo), inglês (avançado), espanhol (intermediário)",
      ["inglês (B2, certificado)", "espanhol (A2.3, certificado)"])),
    ("inglês intermediário-avançado (B2, certificado)", ("inglês (intermediário-avançado)", ["inglês (B2, certificado)"])),
    ("inglês (avançado, C1)", ("inglês (avançado)", ["inglês (C1)"])),
    ("inglês (avançado), espanhol (básico)", None),  # já no formato novo
    ("inglês (B2)", None),  # só o CEFR: não dá para saber o nível declarado
])
def test_the_old_line_splits_into_declared_level_and_certification(value, expected):
    assert languages.split(value) == expected


def test_levels_read_both_fields_and_the_certification_field_wins():
    rows = languages.levels("inglês avançado (B2, certificado), espanhol (básico)", "inglês (C1, IELTS)")

    assert rows["ingles"] == {"name": "inglês", "declared": "avançado", "certification": "C1, IELTS"}
    assert rows["espanhol"] == {"name": "espanhol", "declared": "básico", "certification": None}


# --- migração --------------------------------------------------------------------------------------

def test_the_old_line_becomes_a_proposal_with_the_original_text(skill):
    result = profile(skill)

    migration = result["migration"]
    assert migration["kind"] == "idiomas" and migration["section"] == "Respostas padrão"
    assert migration["fields"] == [
        {"label": "Idiomas", "value": "português (nativo), inglês (avançado), espanhol (intermediário)",
         "from": "português (nativo), inglês avançado (B2, certificado), espanhol intermediário (A2.3, certificado)"},
        {"label": "Certificações de idiomas", "value": "inglês (B2, certificado), espanhol (A2.3, certificado)",
         "from": "português (nativo), inglês avançado (B2, certificado), espanhol intermediário (A2.3, certificado)"},
    ]
    assert any("apply_profile_migration" in w for w in result["warnings"])
    idiomas = next(f for s in result["sections"] for f in s["fields"] if f["label"] == "Idiomas")
    assert idiomas["status"] == "ok"  # continua valendo até migrar


def test_applying_it_splits_the_line_drops_the_old_note_and_keeps_the_others(skill):
    written = ProfileFiles(skill).apply_migration()

    text = (skill / "perfil.md").read_text(encoding="utf-8")
    assert written == {"kind": "idiomas", "written": ["Idiomas", "Certificações de idiomas"], "to_fill": []}
    assert ("- Idiomas: português (nativo), inglês (avançado), espanhol (intermediário)\n"
            f"  - {languages.LANGUAGES_NOTE}\n"
            "  - Libras: só leitura.\n"
            "- Certificações de idiomas: inglês (B2, certificado), espanhol (A2.3, certificado)\n"
            f"  - {languages.CERTIFICATIONS_NOTE}\n"
            "- Parentes na empresa: não\n") in text
    assert "arredondar" not in text
    example = (skill / "perfil.example.md").read_text(encoding="utf-8")
    assert "- Idiomas: português (nativo), inglês (avançado)\n- Certificações de idiomas: <...>\n" in example
    assert "migration" not in profile(skill)


def test_an_existing_certification_field_is_kept_and_completed(skill):
    text = OLD.replace("- Parentes na empresa: não\n",
                       "- Certificações de idiomas: inglês (C1, IELTS)\n- Parentes na empresa: não\n")
    (skill / "perfil.md").write_text(text, encoding="utf-8")

    proposal = profile(skill)["migration"]["fields"][1]
    ProfileFiles(skill).apply_migration()

    assert proposal["value"] == "inglês (C1, IELTS), espanhol (A2.3, certificado)"
    after = (skill / "perfil.md").read_text(encoding="utf-8")
    assert after.count("Certificações de idiomas:") == 1
    assert "- Certificações de idiomas: inglês (C1, IELTS), espanhol (A2.3, certificado)\n" in after


def test_nothing_to_migrate_is_an_error(skill):
    ProfileFiles(skill).apply_migration()

    with pytest.raises(Exception, match="Não há proposta"):
        ProfileFiles(skill).apply_migration()


# --- pelo MCP --------------------------------------------------------------------------------------

DIVERSITY_OLD = "\n## Diversidade e inclusão\n- Diversidade:\n  - Sexo: Masculino\n"


async def test_proposals_come_one_at_a_time_and_each_refusal_is_remembered(db_path, skill):
    (skill / "perfil.md").write_text(OLD + DIVERSITY_OLD, encoding="utf-8")
    server = build_server(db_path, vault=Vault(skill / "cofre.json", FakeBackend()))
    async with Client(server) as client:
        first = (await client.call_tool("get_profile", {})).structured_content["migration"]
        declined = (await client.call_tool("apply_profile_migration", {"accept": False})).structured_content
        second = (await client.call_tool("get_profile", {})).structured_content["migration"]
        accepted = (await client.call_tool("apply_profile_migration", {"accept": True})).structured_content
        after = (await client.call_tool("get_profile", {})).structured_content

    assert first["kind"] == "diversidade" and declined == {"declined": True, "kind": "diversidade"}
    assert second["kind"] == "idiomas"
    assert accepted["kind"] == "idiomas"
    assert "migration" not in after  # a de diversidade foi recusada e não volta
    assert "Certificações de idiomas" in (skill / "perfil.md").read_text(encoding="utf-8")


async def test_a_refusal_saved_by_the_previous_version_still_counts(db_path, skill):
    (skill / "perfil.md").write_text(OLD + DIVERSITY_OLD, encoding="utf-8")
    diversity_id = profile(skill)["migration"]["id"]
    with connect(db_path) as conn:
        Repo(conn).set_state("profile_migration_declined", diversity_id)  # formato antigo: um id só
    server = build_server(db_path, vault=Vault(skill / "cofre.json", FakeBackend()))
    async with Client(server) as client:
        shown = (await client.call_tool("get_profile", {})).structured_content["migration"]
        await client.call_tool("apply_profile_migration", {"accept": False})

    assert shown["kind"] == "idiomas"
    with connect(db_path) as conn:
        assert set(json.loads(Repo(conn).get_state("profile_migration_declined"))) == {diversity_id, shown["id"]}
