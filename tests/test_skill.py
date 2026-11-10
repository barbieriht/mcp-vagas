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
            # Os arquivos pessoais ficam fora do git: num clone novo, basta existir o exemplo.
            example = SKILL_DIR / target.replace(".md", ".example.md")
            assert (SKILL_DIR / target).exists() or example.exists(), f"{doc.name} -> {target}"


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


def test_search_flow_runs_in_batch_with_step_by_step_as_plan_b():
    text = (SKILL_DIR / "buscar.md").read_text(encoding="utf-8")
    plan_b = text[text.index("## Plano B"):]

    assert text.index("`start_search_run`") < text.index("`get_search_run`") < text.index("## Plano B")
    assert plan_b.index("`suggest_job_searches`") < plan_b.index("`search_jobs`") < plan_b.index("`triage_job`")


def test_master_update_uses_diff_master():
    text = (SKILL_DIR / "curriculo.md").read_text(encoding="utf-8")

    assert text.index("`import_linkedin_profile`") < text.index("`diff_master`") < text.rindex("`approve_master`")


def test_application_flow_uses_profile_and_selection_tools():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")

    assert text.index("`suggest_tailored_selection`") < text.index("`create_tailored_resume`")
    assert "`add_profile_field`" in text[text.index("## Campos novos do perfil"):]


def test_identity_documents_are_left_to_the_browser_extension():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    form = text[text.index("**Perfil:**"):text.index("**Acesso:**")]
    review = text[text.index("5. **Revisão antes do envio.**"):text.index("6. **Registro final.**")]

    assert "extensão do Chrome" in form and "não os digite" in form and "`pending`" in form
    assert "get_sensitive_field" not in text and "sensitive_autofill" not in text
    assert "confirme na janela da extensão" in review


def test_resume_upload_is_left_to_the_browser_extension_with_the_path_as_fallback():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    upload = text[text.index("**Anexo:**"):text.index("**Pretensão salarial:**")]

    assert "extensão do Chrome" in upload and "`create_tailored_resume`" in upload
    assert "Não anexe você mesmo" in upload and "`windows_path`" in upload and "`pendente_usuario`" in upload


def test_terms_of_use_are_left_to_the_browser_extension_but_declarations_are_not():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    consent = text[text.index("**Consentimentos:**"):text.index("4. **Bloqueios.**")]

    assert "extensão do Chrome" in consent and "Não as marque" in consent and "`pending`" in consent
    assert "Declaro que" in consent and "perfil" in consent


def test_work_list_command_and_search_summary_use_the_tool():
    command = (SKILL_DIR.parent / "comandos" / "work-list" / "SKILL.md").read_text(encoding="utf-8")
    search = (SKILL_DIR / "buscar.md").read_text(encoding="utf-8")

    assert "`work_list`" in command and "`list_applications`" not in command
    assert "`work_list`" in search[search.index("5. **Resumo.**"):]


def test_application_reads_the_profile_through_the_tool():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")

    assert text.index("`get_profile`") < text.index("**Acesso:**")


def test_skill_asks_about_paths_on_first_use_before_any_flow():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    first_use = text[text.index("## Primeiro uso"):text.index("## Escolha o fluxo")]

    assert "`get_config`" in first_use and "`set_config`" in first_use and "`needs_setup`" in first_use
    assert "sugira" in first_use.lower() and "pergunte" in first_use.lower()


def test_post_application_tests_are_pending_items_not_blockers():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    final = text[text.index("6. **Registro final.**"):text.index("## Campos novos do perfil")]

    assert "teste" in final.lower() and "`pending`" in final and "`aplicada`" in final
    assert "próxima vaga" in final and "não faça" in final.lower()


def test_batches_continue_and_report_pendencies_at_the_end():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    batch = text[text.index("## Várias vagas"):text.index("## Triagem")]

    assert "não espere" in batch.lower() and "ao final" in batch.lower()
    assert "`aplicada`" in batch and "`pendente_usuario`" in batch and "`encerrada`" in batch


def test_attachment_that_cannot_be_automated_leaves_the_tab_open_and_names_the_file():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    attach = text[text.index("**Anexo:**"):text.index("**Pretensão salarial:**")]

    assert "deixe a aba aberta" in attach and "`pendente_usuario`" in attach
    assert "windows_path" in attach and "`resume_id`" in text
    assert "seguir" in attach.lower() or "siga" in attach.lower()


def test_open_tabs_are_limited_by_the_configured_value():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    tabs = text[text.index("## Abas abertas"):text.index("## Campos novos do perfil")]

    assert "`max_open_tabs`" in tabs and "`get_config`" in tabs
    assert "`a_aplicar`" in tabs and "resumo" in tabs.lower()


def test_browser_permissions_are_suggested_once_before_the_first_application():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")

    assert "Automatically approve" in text and "Always allow actions on this site" in text
    assert text.index("Automatically approve") < text.index("1. **Triagem.**")


def test_batch_fills_forms_up_to_the_tab_limit_and_reviews_them_together():
    flow = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    review = flow[flow.index("5. **Revisão antes do envio.**"):flow.index("6. **Registro final.**")]
    tabs = flow[flow.index("## Abas abertas"):flow.index("## Campos novos do perfil")]
    batch = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    batch = batch[batch.index("## Várias vagas"):batch.index("## Triagem")]

    assert "**Em lote:**" in review and "pronta para envio" in review and "próxima vaga" in review
    assert "pronta para envio" in tabs and "revisão do lote" in tabs.lower()
    assert "não pare para revisar" in batch.lower() and "`max_open_tabs`" in batch


def test_hybrid_or_remote_availability_is_yes_only_in_the_region_of_the_accepted_cities():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    rule = text[text.index("**Disponibilidade para remoto, híbrido ou presencial:**"):text.index("**Anexo:**")]

    assert "[criterios-triagem.md](criterios-triagem.md)" in rule and "Locais aceitos para híbrido e presencial" in rule
    assert '"sim"' in rule and "região" in rule
    assert "pergunte ao usuário antes" in rule and "`pending`" in rule


def test_login_prefers_linkedin_then_the_google_account():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    access = text[text.index("**Acesso:**"):text.index("**Vaga encerrada:**")]
    setup = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert access.index("LinkedIn") < access.index("Google") and "`login_email`" in access
    assert "Sempre que" in access and "nenhum dos dois" in access
    assert "segunda opção" in setup and "`login_email`" in setup


def test_intermediate_buttons_are_clicked_and_the_final_one_follows_auto_submit():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    review = text[text.index("5. **Revisão antes do envio.**"):text.index("6. **Registro final.**")]
    form = text[text.index("3. **Formulário.**"):text.index("4. **Bloqueios.**")]

    assert "Salvar e continuar" in form and "sem perguntar" in form
    assert "`auto_submit`" in review and '"sim"' in review
    for condition in ("`pending`", "extensão", "pretensão", "carta de apresentação"):
        assert condition in review
    assert "enviada automaticamente" in review


def test_cover_letter_is_left_blank_when_optional_and_written_for_review_when_required():
    text = (SKILL_DIR / "candidatar.md").read_text(encoding="utf-8")
    letter = text[text.index("**Carta de apresentação:**"):text.index("4. **Bloqueios.**")]

    assert "opcional" in letter and "em branco" in letter
    assert "obrigatória" in letter and "revisão" in letter


def test_versioned_skill_files_do_not_name_a_specific_person():
    # A Skill é pública: quem a usa é "o usuário"; o nome real só aparece no perfil.md (fora do git).
    skill_root = SKILL_DIR.parent
    files = [p for p in skill_root.rglob("*.md") if p.name not in {"perfil.md", "politica-salarial.md", "criterios-triagem.md"}]
    assert files
    for path in files:
        assert "Thiago" not in path.read_text(encoding="utf-8"), path
