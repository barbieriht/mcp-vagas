import importlib.util
import json
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "instalar_claude_code.py"
spec = importlib.util.spec_from_file_location("instalar_claude_code", SCRIPT)
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)
REPO = Path(__file__).resolve().parents[1]


def test_skill_dirs_are_main_skill_and_every_command():
    names = [d.name for d in inst.skill_dirs(REPO)]

    assert names[0] == "candidaturas"
    assert set(names[1:]) == {"generate-master-resume", "search-jobs", "apply", "screen", "work-list", "pending",
                              "export-applications"}


def test_link_is_created_kept_and_fixed(tmp_path):
    target, other = tmp_path / "skill", tmp_path / "other"
    target.mkdir()
    other.mkdir()
    link = tmp_path / "home" / "skills" / "skill"

    assert inst.ensure_link(link, target) == "criado"
    assert inst.ensure_link(link, target) == "ok"
    inst.remove_link(link)
    inst.make_link(link, other)  # symlink no Linux; junção no Windows (não exige privilégio)
    assert inst.ensure_link(link, target) == "atualizado"
    assert link.resolve() == target.resolve()


def test_real_directory_is_never_replaced(tmp_path):
    target = tmp_path / "skill"
    target.mkdir()
    real = tmp_path / "skills" / "skill"
    real.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        inst.ensure_link(real, target)
    assert real.is_dir() and not real.is_symlink()


def test_mcp_registration_detection(tmp_path):
    claude_json = tmp_path / ".claude.json"
    assert inst.mcp_registered(claude_json) is False
    claude_json.write_text('{"mcpServers": {"vagas": {}}}')
    assert inst.mcp_registered(claude_json) is True


def test_personal_links_point_from_next_to_the_db_to_the_skill(tmp_path):
    links = inst.personal_links(tmp_path / "data", REPO)

    assert links == [(tmp_path / "data" / name, REPO / "skill" / "candidaturas" / name)
                     for name in ("politica-salarial.md", "criterios-triagem.md")]


def test_native_windows_registration_points_the_server_to_the_skill_without_symlinks(tmp_path):
    data, repo = tmp_path / "vagas", tmp_path / "repo"
    python = data / "venv" / "Scripts" / "python.exe"

    command = inst.mcp_add_command(python, data, repo, native_windows=True)

    skill = repo / "skill" / "candidaturas"
    assert command[:5] == ["claude", "mcp", "add", "vagas", "--scope"]
    assert command[-3:] == [str(python), "-m", "vagas.server"]
    for variable in (f"VAGAS_DB={data / 'vagas.db'}", f"VAGAS_SKILL_DIR={skill}",
                     f"VAGAS_SALARY_POLICY={skill / 'politica-salarial.md'}",
                     f"VAGAS_TRIAGE_CRITERIA={skill / 'criterios-triagem.md'}"):
        assert variable in command


def test_linux_registration_relies_on_the_links_next_to_the_db(tmp_path):
    data = tmp_path / "vagas"
    command = inst.mcp_add_command(data / "venv/bin/python", data, tmp_path / "repo", native_windows=False)

    assert f"VAGAS_DB={data / 'vagas.db'}" in command
    assert not any(part.startswith("VAGAS_SKILL_DIR=") for part in command)


def test_stable_python_and_data_dir_follow_the_platform(tmp_path):
    assert inst.stable_python(tmp_path, native_windows=True) == tmp_path / "venv" / "Scripts" / "python.exe"
    assert inst.stable_python(tmp_path, native_windows=False) == tmp_path / "venv" / "bin" / "python"


def test_browser_host_folders_on_linux_and_macos(tmp_path):
    linux = inst.browser_host_dirs(tmp_path, macos=False)
    macos = inst.browser_host_dirs(tmp_path, macos=True)

    assert tmp_path / ".config/google-chrome/NativeMessagingHosts" in linux
    assert tmp_path / ".config/chromium/NativeMessagingHosts" in linux
    assert tmp_path / "Library/Application Support/Google/Chrome/NativeMessagingHosts" in macos
    assert all(d.name == "NativeMessagingHosts" for d in linux + macos)


def test_host_script_runs_the_stable_python_with_quoted_variables(tmp_path):
    python = tmp_path / "meu venv" / "bin" / "python"

    script = inst.host_script(python, {"VAGAS_DB": str(tmp_path / "a b" / "vagas.db")})

    assert script.startswith("#!/bin/sh\n")
    assert f"'VAGAS_DB={tmp_path / 'a b' / 'vagas.db'}'" in script
    assert f"'{python}' -m vagas.autofill_host" in script


def test_native_host_is_registered_in_the_installed_browsers_only(tmp_path):
    home, data = tmp_path / "home", tmp_path / "data"
    (home / ".config/chromium").mkdir(parents=True)  # só o Chromium instalado

    manifests = inst.install_native_host(data, data / "venv/bin/python", home, macos=False)

    assert manifests == [home / ".config/chromium/NativeMessagingHosts/com.barbieriht.vagas.json"]
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    script = data / "vagas-host.sh"
    assert manifest["path"] == str(script) and manifest["type"] == "stdio"
    assert manifest["allowed_origins"] == ["chrome-extension://ebbppobebhjfconpancjbjpijelcnimc/"]
    assert os.access(script, os.X_OK)


def test_without_any_browser_folder_the_host_goes_to_google_chrome(tmp_path):
    manifests = inst.install_native_host(tmp_path / "data", tmp_path / "python", tmp_path / "home", macos=True)

    assert manifests == [tmp_path / "home/Library/Application Support/Google/Chrome/NativeMessagingHosts"
                         / "com.barbieriht.vagas.json"]


def test_host_uses_the_same_db_as_the_claude_code_registration(tmp_path):
    inst.install_native_host(tmp_path / "data", tmp_path / "python", tmp_path / "home", macos=False,
                             registered={"VAGAS_DB": "/outro/vagas.db", "VAGAS_RESUME_OUT": "/pdfs"})

    script = (tmp_path / "data" / "vagas-host.sh").read_text(encoding="utf-8")
    assert "VAGAS_DB=/outro/vagas.db" in script and "VAGAS_RESUME_OUT" not in script
