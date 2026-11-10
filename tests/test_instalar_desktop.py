import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "instalar_desktop.py"
spec = importlib.util.spec_from_file_location("instalar_desktop", SCRIPT)
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)

ENV = {"VAGAS_DB": "/home/u/.local/share/vagas/vagas.db", "VAGAS_RESUME_OUT": "/mnt/c/Users/T/Curriculos"}


def write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("relative", [
    "local/Claude-Data/claude_abc123/claude_desktop_config.json",
    "roaming/Claude/claude_desktop_config.json",
    "local/Packages/Claude_abc123/LocalCache/Roaming/Claude/claude_desktop_config.json",
])
def test_finds_config_of_each_installation_type(tmp_path, relative):
    config = write(tmp_path / relative, "{}")

    assert inst.find_config(tmp_path / "local", tmp_path / "roaming") == config


def test_missing_config_returns_none(tmp_path):
    assert inst.find_config(tmp_path / "local", tmp_path / "roaming") is None


def test_merge_adds_server_and_keeps_everything_else():
    config = {"preferences": {"theme": "dark"}, "mcpServers": {"outro": {"command": "x"}}}

    merged = inst.merge_config(config, "Ubuntu-22.04", ENV, "/home/u/venv/bin/python")

    assert merged["preferences"] == {"theme": "dark"}
    assert merged["mcpServers"]["outro"] == {"command": "x"}
    assert merged["mcpServers"]["vagas"] == {
        "command": "wsl.exe",
        "args": ["-d", "Ubuntu-22.04", "-e", "env",
                 "VAGAS_DB=/home/u/.local/share/vagas/vagas.db", "VAGAS_RESUME_OUT=/mnt/c/Users/T/Curriculos",
                 "/home/u/venv/bin/python", "-m", "vagas.server"],
    }
    assert "mcpServers" not in config or "vagas" not in config["mcpServers"]


def test_env_comes_from_claude_code_registration(tmp_path):
    claude_json = write(tmp_path / ".claude.json", json.dumps({"mcpServers": {"vagas": {"env": {
        "VAGAS_DB": "/db/vagas.db", "VAGAS_RESUME_OUT": "/mnt/c/out", "VAGAS_EXPORT_DIR": "/mnt/c/exp"}}}}))

    assert inst.desktop_env(claude_json, "Maria", tmp_path / "home") == {
        "VAGAS_DB": "/db/vagas.db", "VAGAS_RESUME_OUT": "/mnt/c/out", "VAGAS_EXPORT_DIR": "/mnt/c/exp"}


def test_env_defaults_without_claude_code_registration(tmp_path):
    assert inst.desktop_env(tmp_path / "nada.json", "Maria", tmp_path / "home") == {
        "VAGAS_DB": str(tmp_path / "home/.local/share/vagas/vagas.db")}  # pastas: perguntadas no primeiro uso


@pytest.fixture
def skill(tmp_path):
    d = tmp_path / "candidaturas"
    for name in ("SKILL.md", "candidatar.md", "buscar.md", "curriculo.md", "perfil.example.md",
                 "politica-salarial.example.md", "criterios-triagem.example.md"):
        write(d / name)
    write(d / "perfil.md", "- Nome: Maria\n")
    write(d / "politica-salarial.md", "- Modo: minimo\n")
    write(d / "criterios-triagem.md", "- Cargos alvo: data_scientist\n")
    return d


def test_unfilled_lists_placeholders_and_missing_files(skill):
    assert inst.unfilled(skill) == []

    write(skill / "politica-salarial.md", "- Modo: minimo\n- Multiplicador PJ: <PREENCHER, ex.: 1.4>\n")
    (skill / "perfil.md").unlink()

    assert inst.unfilled(skill) == [
        "perfil.md: arquivo não existe (copie de perfil.example.md)",
        "politica-salarial.md:2: - Multiplicador PJ: <PREENCHER, ex.: 1.4>",
    ]


def test_zip_has_skill_folder_with_personal_files_and_without_examples(skill, tmp_path):
    dest = tmp_path / "out" / "candidaturas.zip"

    inst.build_zip(skill, dest)

    with zipfile.ZipFile(dest) as z:
        assert sorted(z.namelist()) == [
            "candidaturas/SKILL.md", "candidaturas/buscar.md", "candidaturas/candidatar.md",
            "candidaturas/criterios-triagem.md", "candidaturas/curriculo.md", "candidaturas/perfil.md",
            "candidaturas/politica-salarial.md",
        ]


def test_command_zips_have_one_folder_each(tmp_path):
    commands = tmp_path / "comandos"
    for name in ("apply", "screen"):
        write(commands / name / "SKILL.md", f"---\nname: {name}\n---\n")

    zips = inst.build_command_zips(commands, tmp_path / "out")

    assert [z.name for z in zips] == ["apply.zip", "screen.zip"]
    with zipfile.ZipFile(zips[0]) as z:
        assert z.namelist() == ["apply/SKILL.md"]


def test_personal_link_is_created_kept_and_never_replaces_a_real_file(skill, tmp_path):
    data = tmp_path / "data"

    assert inst.link_personal(data, skill, "politica-salarial.md") == "criado"
    assert (data / "politica-salarial.md").read_text() == "- Modo: minimo\n"
    assert inst.link_personal(data, skill, "politica-salarial.md") == "ok"

    (data / "politica-salarial.md").unlink()
    write(data / "politica-salarial.md", "própria\n")
    assert "mantido" in inst.link_personal(data, skill, "politica-salarial.md")
    assert (data / "politica-salarial.md").read_text() == "própria\n"


def test_extension_id_is_fixed_by_the_manifest_key():
    manifest = json.loads((SCRIPT.parents[1] / "extension" / "manifest.json").read_text(encoding="utf-8"))

    assert inst.extension_id(manifest["key"]) == "ebbppobebhjfconpancjbjpijelcnimc"


def test_native_host_only_answers_the_extension():
    manifest = inst.host_manifest("C:\\Users\\T\\AppData\\Local\\vagas\\vagas-host.bat", "abc")

    assert manifest == {"name": "com.barbieriht.vagas", "description": manifest["description"],
                        "path": "C:\\Users\\T\\AppData\\Local\\vagas\\vagas-host.bat", "type": "stdio",
                        "allowed_origins": ["chrome-extension://abc/"]}


def test_native_host_runs_the_stable_server_copy_in_wsl():
    bat = inst.host_bat("Ubuntu", "/home/u/.local/share/vagas/venv/bin/python", ENV)

    assert bat.startswith("@echo off\r\n")
    assert ('wsl.exe -d Ubuntu -e env "VAGAS_DB=/home/u/.local/share/vagas/vagas.db" '
            '"/home/u/.local/share/vagas/venv/bin/python" -m vagas.autofill_host\r\n') in bat
    assert "VAGAS_RESUME_OUT" not in bat


def test_native_host_is_registered_for_the_current_user_in_chrome():
    command = inst.registry_command("C:\\x\\com.barbieriht.vagas.json")

    assert command == ["reg.exe", "add", "HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.barbieriht.vagas",
                       "/ve", "/t", "REG_SZ", "/d", "C:\\x\\com.barbieriht.vagas.json", "/f"]
