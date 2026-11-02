"""A Skill "candidaturas" só pode citar tools, parâmetros, status e campos que o servidor conhece."""

import re
from pathlib import Path

import pytest
from mcp import Client

pytestmark = pytest.mark.anyio

SKILL_DIR = Path(__file__).resolve().parents[1] / "skill" / "candidaturas"
# Arquivos de dados pessoais (e seus exemplos) não são instruções da Skill.
INSTRUCTIONS = sorted(p for p in SKILL_DIR.glob("*.md") if not p.name.startswith(("perfil", "politica-salarial", "criterios-triagem")))
SNAKE_IN_BACKTICKS = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")
SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _schema_words(node, found):
    if isinstance(node, dict):
        found.update(node.get("properties", {}))
        found.update(str(v) for v in node.get("enum", []))
        if "const" in node:
            found.add(str(node["const"]))
        for value in node.values():
            _schema_words(value, found)
    elif isinstance(node, list):
        for value in node:
            _schema_words(value, found)


async def known_identifiers(server):
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    known = {tool.name for tool in tools}
    for tool in tools:
        _schema_words(tool.input_schema, known)
        known.update(SNAKE.findall(tool.description or ""))
    return known


def test_skill_has_frontmatter_and_instruction_files():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert text.startswith("---\nname: candidaturas\ndescription: ")
    assert {p.name for p in INSTRUCTIONS} >= {"SKILL.md", "candidatar.md", "buscar.md", "curriculo.md"}


def test_linked_files_exist():
    for doc in INSTRUCTIONS:
        for target in re.findall(r"\]\(([^)#]+\.md)\)", doc.read_text(encoding="utf-8")):
            assert (SKILL_DIR / target).exists() or target.endswith(".example.md"), f"{doc.name} -> {target}"


async def test_skill_cites_only_identifiers_the_server_knows(server):
    known = await known_identifiers(server)

    unknown = {
        (doc.name, identifier)
        for doc in INSTRUCTIONS
        for identifier in SNAKE_IN_BACKTICKS.findall(doc.read_text(encoding="utf-8"))
        if identifier not in known
    }

    assert unknown == set()


async def test_consistency_check_catches_a_renamed_tool(server, tmp_path):
    known = await known_identifiers(server)

    assert "find_application" in known
    assert "find_applications" not in known


def test_skill_routes_to_master_resume_flow():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    description = skill.split("\n")[2]

    assert "(curriculo.md)" in skill
    assert "currículo geral" in description


COMMANDS_DIR = SKILL_DIR.parent / "comandos"
COMMANDS = sorted(COMMANDS_DIR.glob("*/SKILL.md"))
EXPECTED_COMMANDS = {"generate-master-resume", "search-jobs", "apply", "screen", "work-list", "pending",
                     "export-applications"}


def frontmatter(path):
    _, header, body = path.read_text(encoding="utf-8").split("---", 2)
    fields = dict(line.split(": ", 1) for line in header.strip().splitlines())
    return fields, body


def test_all_commands_exist():
    assert {path.parent.name for path in COMMANDS} == EXPECTED_COMMANDS


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.parent.name)
def test_command_is_user_invoked_and_named_after_its_folder(path):
    fields, body = frontmatter(path)

    assert fields["name"] == path.parent.name
    assert fields["disable-model-invocation"] == "true"
    assert fields["description"]
    assert "$ARGUMENTS" in body or path.parent.name in {"work-list", "pending", "export-applications"}


@pytest.mark.parametrize("name", ["apply", "screen"])
def test_commands_with_required_argument_ask_for_it(name):
    fields, body = frontmatter(COMMANDS_DIR / name / "SKILL.md")

    assert "argument-hint" in fields
    assert "peça" in body.lower()


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.parent.name)
def test_command_points_to_existing_flow(path):
    body = frontmatter(path)[1]

    for flow in re.findall(r"\b([a-z]+\.md)\b", body):
        assert (SKILL_DIR / flow).exists(), flow


async def test_commands_cite_only_identifiers_the_server_knows(server):
    known = await known_identifiers(server)

    unknown = {(p.parent.name, i) for p in COMMANDS for i in SNAKE_IN_BACKTICKS.findall(p.read_text()) if i not in known}

    assert unknown == set()


def test_triage_lets_the_mcp_read_the_salary_policy():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    step = next(line for line in text.splitlines() if "Chame `evaluate_salary`" in line)

    assert "my_min" not in step and "pj_multiplier" not in step


def test_triage_starts_with_triage_job_and_keeps_manual_steps_as_plan_b():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    triage = text[text.index("## Triagem"):]

    assert triage.index("`triage_job`") < triage.index("plano B") < triage.index("`find_application`")
    # Critérios fixos ficam no arquivo pessoal, não no texto da Skill.
    assert "CI&T" not in text and "criterios-triagem.md" in triage
