import json
from pathlib import Path

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from vagas import system
from vagas.config import SETTINGS, config_path, normalize_path, resolve, split_domains, suggest_dirs
from vagas.server import build_server

pytestmark = pytest.mark.anyio


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content


def test_precedence_is_env_then_config_file_then_default(db_path, monkeypatch, tmp_path):
    assert resolve("export_dir", db_path) == (db_path.parent / "exports", "default")
    assert resolve("resume_out", db_path) == (None, "unset")

    config_path(db_path).write_text(f"export_dir = '{tmp_path / 'csv'}'\n", encoding="utf-8")
    assert resolve("export_dir", db_path) == (tmp_path / "csv", "config")

    monkeypatch.setenv("VAGAS_EXPORT_DIR", str(tmp_path / "env"))
    assert resolve("export_dir", db_path) == (tmp_path / "env", "env")


def test_config_file_location_can_be_overridden(db_path, monkeypatch, tmp_path):
    monkeypatch.setenv("VAGAS_CONFIG", str(tmp_path / "outro.toml"))

    assert config_path(db_path) == tmp_path / "outro.toml"


def test_suggestions_prefer_the_windows_documents_folder_on_wsl(tmp_path):
    users = tmp_path / "Users"
    (users / "Maria" / "Documents").mkdir(parents=True)
    (users / "Public" / "Documents").mkdir(parents=True)
    home = tmp_path / "home"

    suggestions = suggest_dirs("resume_out", users_root=users, home=home)

    assert suggestions == [str(users / "Maria" / "Documents" / "Curriculos"), str(home / "Documents" / "Curriculos")]


@pytest.mark.parametrize("system_folder", ["Usuário Padrão", "Default User", "Todos os Usuários", "Público", "defaultuser0", "TEMP"])
def test_suggestions_skip_windows_system_folders(tmp_path, system_folder):
    users = tmp_path / "Users"
    (users / "Maria" / "Documents").mkdir(parents=True)
    (users / system_folder / "Documents").mkdir(parents=True)

    suggestions = suggest_dirs("resume_out", users_root=users, home=tmp_path / "home")

    assert suggestions == [str(users / "Maria" / "Documents" / "Curriculos"),
                           str(tmp_path / "home" / "Documents" / "Curriculos")]


def test_suggestions_without_windows_use_the_home_folder(tmp_path):
    assert suggest_dirs("export_dir", users_root=tmp_path / "nao-existe", home=tmp_path) == [
        str(tmp_path / "Documents" / "Vagas")]


async def test_first_use_lists_everything_to_configure(db_path):
    async with Client(build_server(db_path)) as client:
        result = payload(await client.call_tool("get_config", {}))

    assert result["needs_setup"] == ["resume_out", "export_dir", "master_resume", "login_email"]
    assert result["config_file"] == str(config_path(db_path))
    resume_out = result["settings"]["resume_out"]
    assert resume_out["source"] == "unset" and resume_out["value"] is None and resume_out["suggestions"]
    assert result["settings"]["export_dir"]["default"] == str(db_path.parent / "exports")
    assert result["settings"]["master_resume"]["default"] == str(db_path.parent / "curriculo.yaml")


async def test_set_config_saves_creates_the_folder_and_stops_asking(db_path, tmp_path):
    target = tmp_path / "pdfs" / "novos"
    async with Client(build_server(db_path)) as client:
        saved = payload(await client.call_tool("set_config", {"key": "resume_out", "value": str(target)}))
        result = payload(await client.call_tool("get_config", {}))

    assert saved["value"] == str(target) and saved["source"] == "config" and saved["warnings"] == []
    assert target.is_dir()
    assert 'resume_out = ' in config_path(db_path).read_text(encoding="utf-8")
    assert result["needs_setup"] == ["export_dir", "master_resume", "login_email"]
    assert result["settings"]["resume_out"]["value"] == str(target)


async def test_set_config_without_value_confirms_the_default(db_path):
    async with Client(build_server(db_path)) as client:
        saved = payload(await client.call_tool("set_config", {"key": "export_dir"}))
        result = payload(await client.call_tool("get_config", {}))

    assert saved["value"] == str(db_path.parent / "exports") and saved["source"] == "config"
    assert "export_dir" not in result["needs_setup"]


def test_windows_and_home_paths_are_normalized_for_wsl(monkeypatch):
    monkeypatch.setattr(system, "NATIVE_WINDOWS", False)
    assert normalize_path("C:\\Users\\Teste\\Curriculos") == Path("/mnt/c/Users/Teste/Curriculos")
    assert normalize_path("~/pdfs") == Path.home() / "pdfs"


async def test_set_config_keeps_the_other_keys(db_path, tmp_path):
    async with Client(build_server(db_path)) as client:
        await client.call_tool("set_config", {"key": "export_dir", "value": str(tmp_path / "csv")})
        await client.call_tool("set_config", {"key": "resume_out", "value": str(tmp_path / "pdf")})

    assert resolve("export_dir", db_path) == (tmp_path / "csv", "config")
    assert resolve("resume_out", db_path) == (tmp_path / "pdf", "config")


@pytest.mark.parametrize("arguments, message", [
    ({"key": "resume_out", "value": "pasta/relativa"}, "absoluto"),
    ({"key": "outra_coisa", "value": "/tmp/x"}, "resume_out"),
    ({"key": "master_resume", "value": str(Path.home() / "curriculo.txt")}, ".yaml"),  # absoluto em qualquer sistema
    ({"key": "resume_out"}, "value"),
])
async def test_set_config_rejects_bad_input(db_path, arguments, message):
    async with Client(build_server(db_path)) as client:
        result = await client.call_tool("set_config", arguments)

    assert result.is_error and message in result.content[0].text
    assert not config_path(db_path).exists()


async def test_env_variable_wins_and_set_config_warns(db_path, monkeypatch, tmp_path):
    monkeypatch.setenv("VAGAS_RESUME_OUT", str(tmp_path / "env-pdfs"))
    async with Client(build_server(db_path)) as client:
        before = payload(await client.call_tool("get_config", {}))
        saved = payload(await client.call_tool("set_config", {"key": "resume_out", "value": str(tmp_path / "cfg")}))

    assert "resume_out" not in before["needs_setup"]
    assert before["settings"]["resume_out"]["source"] == "env"
    assert saved["value"] == str(tmp_path / "env-pdfs") and saved["source"] == "env"
    assert "VAGAS_RESUME_OUT" in saved["warnings"][0]


async def test_broken_config_file_explains_how_to_fix(db_path):
    config_path(db_path).write_text("resume_out = [", encoding="utf-8")
    async with Client(build_server(db_path)) as client:
        result = await client.call_tool("get_config", {})

    assert result.is_error and str(config_path(db_path)) in result.content[0].text


async def test_configured_folders_are_used_by_the_tools(db_path, tmp_path):
    pdfs, csvs = tmp_path / "pdfs", tmp_path / "csvs"
    draft = tmp_path / "meu" / "geral.yaml"
    async with Client(build_server(db_path)) as client:
        for key, value in (("resume_out", pdfs), ("export_dir", csvs), ("master_resume", draft)):
            await client.call_tool("set_config", {"key": key, "value": str(value)})
        await client.call_tool("save_master_draft", {"resume": fictitious_resume()})
        await client.call_tool("approve_master", {})
        rendered = payload(await client.call_tool("render_master_resume", {"label": "Geral"}))
        await client.call_tool("add_application", {"company": "Nubank", "role": "DS", "source": "linkedin"})
        exported = payload(await client.call_tool("export_csv", {}))

    assert rendered["path"] == str(pdfs / "Fulana_Tal_Resume_Geral.pdf")
    assert exported["path"].startswith(str(csvs))
    assert draft.exists()
    assert json.loads(json.dumps(str(draft)))


async def test_missing_resume_folder_error_points_to_set_config(db_path):
    async with Client(build_server(db_path)) as client:
        await client.call_tool("save_master_draft", {"resume": fictitious_resume()})
        await client.call_tool("approve_master", {})
        result = await client.call_tool("render_master_resume", {})

    assert result.is_error and "set_config" in result.content[0].text and "VAGAS_RESUME_OUT" in result.content[0].text


async def test_server_instructions_tell_the_model_to_check_the_config_first(db_path):
    async with Client(build_server(db_path)) as client:
        instructions = client.instructions

    assert "get_config" in instructions and "set_config" in instructions


async def test_server_instructions_leave_identity_documents_to_the_browser_extension(db_path):
    async with Client(build_server(db_path)) as client:
        instructions = client.instructions

    assert "extensão do Chrome" in instructions and "CPF" in instructions and "termos de uso" in instructions
    assert "anexo do currículo" in instructions and "windows_path" in instructions


async def test_server_instructions_ask_for_job_names_as_markdown_links(db_path):
    async with Client(build_server(db_path)) as client:
        instructions = client.instructions

    assert "[Cargo — Empresa](url)" in instructions


async def set_login(client, method, email=None):
    arguments = {"key": "login_method", "value": method}
    saved = payload(await client.call_tool("set_config", arguments))
    if email:
        payload(await client.call_tool("set_config", {"key": "login_email", "value": email}))
    return saved


@pytest.mark.parametrize("typed, stored", [("linkedin", "linkedin"), ("LinkedIn.", "linkedin"), ("Google", "google"),
                                           (" gmail ", "google"), ("Gmail.", "google")])
async def test_login_method_is_tolerant_and_stored_normalized(db_path, typed, stored):
    async with Client(build_server(db_path)) as client:
        saved = await set_login(client, typed)

    assert saved["value"] == stored and saved["source"] == "config"
    assert resolve("login_method", db_path) == (stored, "config")


async def test_linkedin_comes_first_by_default_and_the_google_account_is_always_asked_as_fallback(db_path):
    async with Client(build_server(db_path)) as client:
        before = payload(await client.call_tool("get_config", {}))
        await set_login(client, "linkedin")
        after = payload(await client.call_tool("get_config", {}))
        tools = {t.name: t for t in (await client.list_tools()).tools}

    method = before["settings"]["login_method"]
    assert (method["value"], method["source"]) == ("linkedin", "default")
    assert "login_method" not in before["needs_setup"]
    assert "login_email" in before["needs_setup"] and "login_email" in after["needs_setup"]
    assert after["settings"]["login_method"]["choices"] == ["linkedin", "google"]
    assert "segunda opção" in tools["get_config"].description


async def test_login_by_google_asks_for_the_account_until_it_is_set(db_path):
    async with Client(build_server(db_path)) as client:
        await set_login(client, "gmail")
        before = payload(await client.call_tool("get_config", {}))
        await set_login(client, "gmail", "Fulano@Example.com")
        after = payload(await client.call_tool("get_config", {}))

    assert before["needs_setup"] == ["resume_out", "export_dir", "master_resume", "login_email"]
    assert "login_email" not in after["needs_setup"]
    assert after["settings"]["login_email"]["value"] == "fulano@example.com"


@pytest.mark.parametrize("arguments, message", [
    ({"key": "login_method", "value": "facebook"}, "linkedin"),
    ({"key": "login_method"}, "value"),
    ({"key": "login_email", "value": "sem-arroba"}, "e-mail"),
    ({"key": "login_email"}, "value"),
])
async def test_login_settings_reject_bad_input(db_path, arguments, message):
    async with Client(build_server(db_path)) as client:
        result = await client.call_tool("set_config", arguments)

    assert result.is_error and message in result.content[0].text
    assert not config_path(db_path).exists()


async def test_login_settings_do_not_create_folders_and_keep_the_paths(db_path, tmp_path):
    async with Client(build_server(db_path)) as client:
        await client.call_tool("set_config", {"key": "export_dir", "value": str(tmp_path / "csv")})
        await set_login(client, "google", "a@b.com")

    assert resolve("export_dir", db_path) == (tmp_path / "csv", "config")
    assert resolve("login_email", db_path) == ("a@b.com", "config")
    assert not (db_path.parent / "google").exists()


async def test_login_env_variable_wins(db_path, monkeypatch):
    monkeypatch.setenv("VAGAS_LOGIN_METHOD", "linkedin")
    async with Client(build_server(db_path)) as client:
        result = payload(await client.call_tool("get_config", {}))

    assert result["settings"]["login_method"]["source"] == "env"
    assert result["settings"]["login_method"]["value"] == "linkedin"


async def test_max_open_tabs_has_a_default_and_is_never_asked(db_path):
    async with Client(build_server(db_path)) as client:
        result = payload(await client.call_tool("get_config", {}))

    tabs = result["settings"]["max_open_tabs"]
    assert (tabs["value"], tabs["source"], tabs["default"]) == ("12", "default", "12")
    assert "max_open_tabs" not in result["needs_setup"]
    assert resolve("max_open_tabs", db_path) == (12, "default")


@pytest.mark.parametrize("typed, stored", [("10", 10), (" 15 ", 15), ("1", 1), ("30", 30)])
async def test_max_open_tabs_is_saved_as_a_number(db_path, typed, stored):
    async with Client(build_server(db_path)) as client:
        saved = payload(await client.call_tool("set_config", {"key": "max_open_tabs", "value": typed}))

    assert saved["value"] == str(stored) and saved["source"] == "config"
    assert resolve("max_open_tabs", db_path) == (stored, "config")
    assert f"max_open_tabs = {stored}" in config_path(db_path).read_text(encoding="utf-8")


def test_max_open_tabs_can_be_edited_by_hand_and_by_env(db_path, monkeypatch):
    config_path(db_path).write_text("max_open_tabs = 8\n", encoding="utf-8")
    assert resolve("max_open_tabs", db_path) == (8, "config")

    monkeypatch.setenv("VAGAS_MAX_OPEN_TABS", "9")
    assert resolve("max_open_tabs", db_path) == (9, "env")


@pytest.mark.parametrize("value, message", [("0", "1 a 30"), ("31", "1 a 30"), ("muitas", "número"), (None, "value")])
async def test_max_open_tabs_rejects_bad_input(db_path, value, message):
    async with Client(build_server(db_path)) as client:
        result = await client.call_tool("set_config", {"key": "max_open_tabs", "value": value})

    assert result.is_error and message in result.content[0].text
    assert not config_path(db_path).exists()


async def test_salary_rule_defaults_to_ceiling_and_is_asked_after_the_first_search(db_path):
    async with Client(build_server(db_path)) as client:
        result = payload(await client.call_tool("get_config", {}))

    rule = result["settings"]["salary_rule"]
    assert (rule["value"], rule["source"], rule["default"]) == ("teto", "default", "teto")
    assert rule["choices"] == ["teto", "meio_termo", "percentil_25", "ponto_baixo"]
    assert "salary_rule" not in result["needs_setup"]
    assert resolve("salary_rule", db_path) == ("teto", "default")


@pytest.mark.parametrize("typed, stored", [
    ("Meio-termo", "meio_termo"), ("meio termo.", "meio_termo"), ("teto por faixa", "teto"),
    ("Percentil 25", "percentil_25"), ("p25", "percentil_25"), ("Ponto baixo", "ponto_baixo"),
])
async def test_salary_rule_is_tolerant_and_stored_normalized(db_path, typed, stored):
    async with Client(build_server(db_path)) as client:
        saved = payload(await client.call_tool("set_config", {"key": "salary_rule", "value": typed}))

    assert saved["value"] == stored and resolve("salary_rule", db_path) == (stored, "config")


async def test_salary_rule_rejects_unknown_values(db_path):
    async with Client(build_server(db_path)) as client:
        result = await client.call_tool("set_config", {"key": "salary_rule", "value": "média"})

    assert result.is_error and "meio_termo" in result.content[0].text


async def test_choosing_the_salary_rule_reevaluates_the_registered_jobs(db_path):
    async with Client(build_server(db_path)) as client:
        saved = payload(await client.call_tool("set_config", {"key": "salary_rule", "value": "meio_termo"}))

    assert saved["reevaluated"] == {"reevaluated": 0, "changed": [], "errors": []}


@pytest.mark.parametrize("typed, stored", [
    ("meuats.com", "meuats.com"),
    ("https://www.MeuATS.com/vagas, carreiras.empresa.com.br; outra.io", "meuats.com, carreiras.empresa.com.br, outra.io"),
])
async def test_autofill_domains_are_optional_and_tolerant(db_path, typed, stored):
    async with Client(build_server(db_path)) as client:
        before = payload(await client.call_tool("get_config", {}))
        saved = payload(await client.call_tool("set_config", {"key": "autofill_domains", "value": typed}))
        bad = await client.call_tool("set_config", {"key": "autofill_domains", "value": "não é domínio"})

    assert before["settings"]["autofill_domains"]["source"] == "unset"
    assert "autofill_domains" not in before["needs_setup"]
    assert saved["value"] == stored
    assert split_domains(saved["value"]) == stored.split(", ")
    assert bad.is_error and "domínio" in bad.content[0].text


@pytest.mark.parametrize("typed, stored", [("gupy.io", "gupy.io"), ("https://Gupy.io, lever.co.", "gupy.io, lever.co")])
async def test_autofill_platforms_accept_only_recruiting_platforms(db_path, typed, stored):
    async with Client(build_server(db_path)) as client:
        before = payload(await client.call_tool("get_config", {}))
        saved = payload(await client.call_tool("set_config", {"key": "autofill_platforms", "value": typed}))
        aggregator = await client.call_tool("set_config", {"key": "autofill_platforms", "value": "linkedin.com"})
        unknown = await client.call_tool("set_config", {"key": "autofill_platforms", "value": "meuats.com"})

    assert before["settings"]["autofill_platforms"]["source"] == "unset"
    assert "autofill_platforms" not in before["needs_setup"]
    assert saved["value"] == stored
    assert aggregator.is_error and "gupy.io" in aggregator.content[0].text
    assert unknown.is_error and "meuats.com" in unknown.content[0].text


@pytest.mark.parametrize("typed, stored", [("sim", "sim"), ("Sim.", "sim"), ("ligado", "sim"), ("não", "nao"),
                                           ("desligado", "nao")])
async def test_auto_submit_is_off_by_default_never_asked_and_tolerant(db_path, typed, stored):
    async with Client(build_server(db_path)) as client:
        before = payload(await client.call_tool("get_config", {}))
        saved = payload(await client.call_tool("set_config", {"key": "auto_submit", "value": typed}))
        tools = {t.name: t for t in (await client.list_tools()).tools}

    setting = before["settings"]["auto_submit"]
    assert (setting["value"], setting["source"]) == ("nao", "default")
    assert "auto_submit" not in before["needs_setup"]
    assert saved["value"] == stored
    assert "auto_submit" in tools["set_config"].description and "pedido" in tools["set_config"].description


def test_the_old_standing_authorization_is_gone(db_path):
    assert "sensitive_autofill" not in SETTINGS


async def test_server_instructions_point_to_the_profile_and_tailored_resume_tools(db_path):
    async with Client(build_server(db_path)) as client:
        instructions = client.instructions

    assert "get_profile" in instructions and "create_tailored_resume" in instructions
