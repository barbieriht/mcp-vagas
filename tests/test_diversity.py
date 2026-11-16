"""Diversidade e inclusão no perfil: um campo por pergunta, migração do formato antigo só com confirmação e
"Possui deficiência" decidindo as vagas exclusivas PcD na triagem."""

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from test_sensitive import FakeBackend
from vagas import diversity
from vagas.db import connect
from vagas.profile_fields import ProfileFiles
from vagas.repo import Repo
from vagas.resume_repo import ResumeStore
from vagas.sensitive import Vault
from vagas.server import build_server
from vagas.triage import Triage

pytestmark = pytest.mark.anyio

HEAD = "# Dados para formulários\n\n## Contato e identificação\n- Nome: Maria Teste\n\n"
LOOSE = HEAD + """## Respostas padrão
- Diversidade: <PREENCHER>
  - Sexo Masculino
  - Homem cisgênero
  - Heterossexual
  - Branco/Latino
- Parentes na empresa: não
"""
GROUPED = HEAD + """## Respostas padrão
- Diversidade (respostas usadas nos formulários; "Prefiro não responder" também é válido):
  - Sexo: Masculino
  - Identidade de gênero: Homem cisgênero
  - Orientação sexual: Heterossexual
  - Raça/etnia: Branco/Latino
- Parentes na empresa: não
"""
NEW = HEAD + """## Diversidade e inclusão
- Possui deficiência: Não
- Cor/raça (IBGE): Prefiro não responder
- Sexo: Masculino
- Identidade de gênero: Homem cisgênero
- Orientação sexual: Heterossexual
"""
EXAMPLE = HEAD + "## Respostas padrão\n- Parentes na empresa: <...>\n"


@pytest.fixture
def skill(tmp_path, monkeypatch):
    folder = tmp_path / "skill"
    folder.mkdir()
    (folder / "perfil.example.md").write_text(EXAMPLE, encoding="utf-8")
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(folder))
    return folder


def profile(skill, text=None):
    if text is not None:
        (skill / "perfil.md").write_text(text, encoding="utf-8")
    return ProfileFiles(skill).get_profile(vault_fields=[])


def field(result, label):
    return next(f for s in result["sections"] for f in s["fields"] if f["label"] == label)


def proposed(result):
    return {f["label"]: f["value"] for f in result["migration"]["fields"]}


# --- respostas e opções ----------------------------------------------------------------------------

@pytest.mark.parametrize("label, text, expected", [
    ("Cor/raça (IBGE)", "Branco/Latino", "Branca"),
    ("Cor/raça (IBGE)", "parda", "Parda"),
    ("Cor/raça (IBGE)", "Pardo/Indígena", None),  # duas opções: não escolhe
    ("Cor/raça (IBGE)", "Latino", None),
    ("Cor/raça (IBGE)", "prefiro não responder", "Prefiro não responder"),
    ("Sexo", "masculino", "Masculino"),
    ("Identidade de gênero", "Não-binárie", "Não-binárie"),  # pergunta aberta: o texto do usuário vale
    ("Possui deficiência", "não possuo", "Não"),
    ("Possui deficiência", "Sim, auditiva", "Sim"),
])
def test_answers_are_mapped_to_the_options_without_guessing(label, text, expected):
    assert diversity.canonical(diversity.question(label), text) == expected


@pytest.mark.parametrize("value, expected", [
    ("Sim", "sim"), ("sim, visual", "sim"), ("Não", "nao"), ("não possuo", "nao"),
    ("Prefiro não responder", "nao_informado"), ("<PREENCHER>", "pendente"), ("", "pendente"),
])
def test_disability_answer(value, expected):
    assert diversity.disability(value) == expected


# --- get_profile -----------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [LOOSE, GROUPED])
def test_old_answers_become_a_proposal_and_are_never_used_before_confirmation(skill, text):
    result = profile(skill, text)

    old = next(f for s in result["sections"] for f in s["fields"] if f["label"].startswith("Diversidade"))
    assert old["status"] == "migrar" and old["notes"] == []  # notas soltas nunca viram resposta
    assert proposed(result) == {"Possui deficiência": None, "Cor/raça (IBGE)": "Branca", "Sexo": "Masculino",
                                "Identidade de gênero": "Homem cisgênero", "Orientação sexual": "Heterossexual"}
    race = next(f for f in result["migration"]["fields"] if f["label"] == "Cor/raça (IBGE)")
    assert race["from"] == "Branco/Latino"
    assert result["migration"]["section"] == "Diversidade e inclusão"
    assert result["warnings"] and not any("Masculino" in w or "Branco" in w for w in result["warnings"])
    assert "Diversidade" not in " ".join(result["to_fill"])


def test_the_new_fields_are_answers_and_prefer_not_to_say_is_valid(skill):
    result = profile(skill, NEW)

    assert field(result, "Cor/raça (IBGE)")["status"] == "ok"
    assert field(result, "Possui deficiência")["value"] == "Não"
    assert "migration" not in result and "warnings" not in result


def test_applying_the_migration_writes_one_field_per_question_and_drops_the_old_block(skill):
    profile(skill, LOOSE)

    written = ProfileFiles(skill).apply_diversity_migration()

    text = (skill / "perfil.md").read_text(encoding="utf-8")
    assert "Diversidade:" not in text and "Sexo Masculino" not in text and "Branco/Latino" not in text
    assert ("## Diversidade e inclusão\n- Possui deficiência: <PREENCHER>\n- Cor/raça (IBGE): Branca\n- Sexo: Masculino\n"
            "- Identidade de gênero: Homem cisgênero\n- Orientação sexual: Heterossexual\n") in text
    assert "- Parentes na empresa: não" in text
    assert written == {"written": ["Cor/raça (IBGE)", "Sexo", "Identidade de gênero", "Orientação sexual"],
                       "to_fill": ["Possui deficiência"]}
    example = (skill / "perfil.example.md").read_text(encoding="utf-8")
    assert "## Diversidade e inclusão\n- Possui deficiência: <...>\n" in example
    after = profile(skill)
    assert "migration" not in after and field(after, "Sexo")["status"] == "ok"
    assert after["to_fill"] == ["Possui deficiência"]


def test_nothing_to_migrate_is_an_error(skill):
    profile(skill, NEW)

    with pytest.raises(Exception, match="formato antigo"):
        ProfileFiles(skill).apply_diversity_migration()


async def test_the_migration_is_offered_once_and_a_refusal_is_remembered(db_path, skill):
    (skill / "perfil.md").write_text(GROUPED, encoding="utf-8")
    server = build_server(db_path, vault=Vault(skill / "cofre.json", FakeBackend()))
    async with Client(server) as client:
        first = (await client.call_tool("get_profile", {})).structured_content
        declined = (await client.call_tool("apply_profile_migration", {"accept": False})).structured_content
        second = (await client.call_tool("get_profile", {})).structured_content
        accepted = (await client.call_tool("apply_profile_migration", {"accept": True})).structured_content

    assert proposed(first)["Sexo"] == "Masculino"
    assert declined == {"declined": True}
    assert "migration" not in second
    assert next(f for s in second["sections"] for f in s["fields"]
                if f["label"].startswith("Diversidade"))["status"] == "preencher"
    assert accepted["written"]  # recusar não impede de aceitar depois, a pedido do usuário
    assert "Possui deficiência: <PREENCHER>" in (skill / "perfil.md").read_text(encoding="utf-8")


# --- triagem: vagas exclusivas PcD -----------------------------------------------------------------

CRITERIA = """\
- Cargos alvo: data_scientist
- Locais aceitos para híbrido e presencial: São Paulo
- Vagas afirmativas que posso disputar: {groups}
"""
PCD_ONLY = "Vaga exclusiva para PcD. Modelos com Python e SQL."


@pytest.fixture
def conn(db_path, tmp_path):
    c = connect(db_path)
    store = ResumeStore(c, tmp_path / "curriculo.yaml")
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    yield c
    c.close()


def recheck(conn, tmp_path, groups, answer):
    criteria = tmp_path / "criterios-triagem.md"
    criteria.write_text(CRITERIA.format(groups=groups), encoding="utf-8")
    app = Repo(conn).add_application(company="Acme", role="Cientista de Dados", source="gupy", status="a_aplicar",
                                     url="https://acme.gupy.io/jobs/1", description=PCD_ONLY)["application"]
    triage = Triage(conn, criteria_path=criteria, draft_path=tmp_path / "curriculo.yaml", disability=lambda: answer)
    triage.apply_criteria_changes()
    return Repo(conn).get(app["id"])


@pytest.mark.parametrize("groups, answer, kept", [
    ("nenhuma", "sim", True),         # o perfil diz que possui: a vaga segue, mesmo sem PcD nos critérios
    ("PcD", "nao", False),            # o perfil diz que não possui: PcD nos critérios não vale
    ("PcD", "nao_informado", False),
    ("PcD", "pendente", False),       # sem resposta: descarta, do lado seguro
    ("PcD", None, True),              # sem o campo no perfil (ou perfil ilegível): vale o critério
    ("nenhuma", None, False),
])
def test_disability_in_the_profile_decides_exclusive_pcd_jobs(conn, tmp_path, groups, answer, kept):
    app = recheck(conn, tmp_path, groups, answer)

    assert (app["status"] == "a_aplicar") is kept
    if not kept and answer is not None:
        assert "Possui deficiência" in app["discard_reason"]


def test_changing_the_disability_answer_rechecks_open_jobs(conn, tmp_path):
    criteria = tmp_path / "criterios-triagem.md"
    criteria.write_text(CRITERIA.format(groups="nenhuma"), encoding="utf-8")
    answer = {"value": "sim"}
    triage = Triage(conn, criteria_path=criteria, draft_path=tmp_path / "curriculo.yaml",
                    disability=lambda: answer["value"])
    triage.apply_criteria_changes()
    app = Repo(conn).add_application(company="Acme", role="Cientista de Dados", source="gupy", status="a_aplicar",
                                     url="https://acme.gupy.io/jobs/1", description=PCD_ONLY)["application"]

    assert triage.apply_criteria_changes() is None
    answer["value"] = "nao"
    result = triage.apply_criteria_changes()

    assert [d["id"] for d in result["discarded"]] == [app["id"]]


def test_saving_the_disability_answer_in_the_panel_rechecks_open_jobs(db_path, skill, tmp_path, monkeypatch):
    from vagas import settings_form

    criteria = tmp_path / "criterios-triagem.md"
    criteria.write_text(CRITERIA.format(groups="PcD"), encoding="utf-8")
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(criteria))
    (skill / "perfil.md").write_text(NEW.replace("Possui deficiência: Não", "Possui deficiência: Sim"), encoding="utf-8")
    conn = connect(db_path)
    app = Repo(conn).add_application(company="Acme", role="Cientista de Dados", source="gupy", status="a_aplicar",
                                     url="https://acme.gupy.io/jobs/1", description=PCD_ONLY)["application"]
    conn.close()

    result = settings_form.save({"profile": {"Diversidade e inclusão/Possui deficiência": "Não"}}, db_path)

    assert result["saved"], result["errors"]
    assert [d["id"] for d in result["rechecked"]["discarded"]] == [app["id"]]
