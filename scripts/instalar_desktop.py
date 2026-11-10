#!/usr/bin/env python3
"""Instala ou atualiza o MCP "vagas" e a Skill "candidaturas" no Claude Desktop (Windows), pelo WSL ou nativo.

Uso, na raiz do repositório (no WSL com python3; no Windows sem WSL, com py scripts\\instalar_desktop.py):
    python3 scripts/instalar_desktop.py                  # tudo
    python3 scripts/instalar_desktop.py --sem-skill      # só servidor e configuração
    python3 scripts/instalar_desktop.py --fechar-desktop # fecha o Desktop no fim, para recarregar
    python3 scripts/instalar_desktop.py --sem-extensao   # sem a extensão do Chrome

Passos: atualiza a cópia estável do servidor, registra o servidor no claude_desktop_config.json
(com backup), testa o servidor pelo wsl.exe, instala a extensão do Chrome (cópia em
%LOCALAPPDATA%\\vagas\\extensao e host de native messaging registrado no HKCU), gera o zip da Skill na pasta Downloads do Windows
e, opcionalmente, fecha o Desktop. O envio do zip (Configurações → Skills) continua manual.
Variáveis já registradas no Claude Code (VAGAS_DB, VAGAS_RESUME_OUT, VAGAS_EXPORT_DIR, VAGAS_CONFIG) são repassadas; as pastas, quando não há variável, o Claude pergunta no primeiro uso (config.toml).
No Windows nativo, o Desktop chama o python.exe da cópia estável (%LOCALAPPDATA%\\vagas\\venv) direto, o banco
fica em %LOCALAPPDATA%\\vagas e o servidor acha a Skill por VAGAS_SKILL_DIR, VAGAS_SALARY_POLICY e
VAGAS_TRIAGE_CRITERIA (no lugar dos symlinks ao lado do banco).
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

NATIVE_WINDOWS = os.name == "nt"
REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skill" / "candidaturas"
COMMANDS_DIR = REPO / "skill" / "comandos"
STABLE_VENV = Path.home() / ".local/share/vagas/venv"
ENV_KEYS = ("VAGAS_DB", "VAGAS_RESUME_OUT", "VAGAS_EXPORT_DIR", "VAGAS_CONFIG")
SKILL_FILES = ("SKILL.md", "candidatar.md", "buscar.md", "curriculo.md", "perfil.md", "politica-salarial.md",
               "criterios-triagem.md")
PERSONAL_FILES = ("perfil.md", "politica-salarial.md", "criterios-triagem.md")
MCP_FILES = ("politica-salarial.md", "criterios-triagem.md")  # lidos pelo servidor, ao lado do banco
EXTENSION_DIR = REPO / "extension"
HOST_NAME = "com.barbieriht.vagas"
HOST_ENV_KEYS = ("VAGAS_DB", "VAGAS_CONFIG", "VAGAS_SENSITIVE_FILE", "VAGAS_SKILL_DIR")  # banco, config, cofre e perfil


# --- Partes puras (testadas) ---------------------------------------------------------------

def find_config(localappdata: Path, appdata: Path) -> Path | None:
    """claude_desktop_config.json da instalação existente: Microsoft Store ou instalador do site."""
    candidates = [
        *sorted(localappdata.glob("Claude-Data/claude_*/claude_desktop_config.json")),
        appdata / "Claude" / "claude_desktop_config.json",
        *sorted(localappdata.glob("Packages/Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json")),
    ]
    return next((path for path in candidates if path.exists()), None)


def merge_config(config: dict, distro: str, env: dict[str, str], python: str) -> dict:
    """Cópia da configuração com o servidor "vagas" acrescentado ou atualizado; o resto fica igual."""
    merged = json.loads(json.dumps(config))
    merged.setdefault("mcpServers", {})["vagas"] = {
        "command": "wsl.exe",
        "args": ["-d", distro, "-e", "env", *(f"{key}={value}" for key, value in env.items()),
                 python, "-m", "vagas.server"],
    }
    return merged


def merge_config_native(config: dict, env: dict[str, str], python: str) -> dict:
    """Windows nativo: o Desktop roda o python.exe da cópia estável, com as variáveis no bloco env."""
    merged = json.loads(json.dumps(config))
    merged.setdefault("mcpServers", {})["vagas"] = {"command": python, "args": ["-m", "vagas.server"], "env": env}
    return merged


def _registered_env(claude_json: Path) -> dict[str, str]:
    try:
        registered = json.loads(claude_json.read_text(encoding="utf-8"))["mcpServers"]["vagas"].get("env", {})
    except (OSError, ValueError, KeyError):
        return {}
    return {key: value for key, value in registered.items() if key in ENV_KEYS}


def native_env(claude_json: Path, data_dir: Path, skill_dir: Path) -> dict[str, str]:
    """Windows nativo: banco na pasta de dados, Skill pelas variáveis, e o que o Claude Code já registrou."""
    env = {"VAGAS_DB": str(data_dir / "vagas.db"), "VAGAS_SKILL_DIR": str(skill_dir),
           "VAGAS_SALARY_POLICY": str(skill_dir / "politica-salarial.md"),
           "VAGAS_TRIAGE_CRITERIA": str(skill_dir / "criterios-triagem.md")}
    env.update(_registered_env(claude_json))
    return env


def desktop_env(claude_json: Path, windows_user: str, home: Path) -> dict[str, str]:
    """Mesmas variáveis do registro no Claude Code, para os dois clientes compartilharem os dados."""
    env = {"VAGAS_DB": str(home / ".local/share/vagas/vagas.db")}
    env.update(_registered_env(claude_json))
    return env


def unfilled(skill_dir: Path) -> list[str]:
    """Arquivos pessoais ausentes e linhas com <PREENCHER>."""
    problems = []
    for name in PERSONAL_FILES:
        path = skill_dir / name
        if not path.exists():
            problems.append(f"{name}: arquivo não existe (copie de {name.replace('.md', '.example.md')})")
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "<PREENCHER" in line:
                problems.append(f"{name}:{number}: {line.strip()}")
    return problems


def link_personal(data_dir: Path, skill_dir: Path, name: str) -> str:
    """Symlink de um arquivo pessoal lido pelo MCP, ao lado do banco, para o da Skill; nunca substitui um arquivo real."""
    link, target = data_dir / name, skill_dir / name
    if link.is_symlink() and link.resolve() == target.resolve():
        return "ok"
    if link.exists() and not link.is_symlink():
        return f"{link} é um arquivo próprio (mantido; o MCP usa esse)"
    if link.is_symlink():
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return "criado"


def build_command_zips(commands_dir: Path, dest_dir: Path) -> list[Path]:
    """Um zip por comando (pasta com o SKILL.md do comando)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    zips = []
    for skill_md in sorted(commands_dir.glob("*/SKILL.md")):
        dest = dest_dir / f"{skill_md.parent.name}.zip"
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(skill_md, f"{skill_md.parent.name}/SKILL.md")
        zips.append(dest)
    return zips


def build_zip(skill_dir: Path, dest: Path) -> None:
    """Zip com a pasta da Skill (instruções e arquivos pessoais; exemplos ficam de fora)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name in SKILL_FILES:
            if (skill_dir / name).exists():
                z.write(skill_dir / name, f"{skill_dir.name}/{name}")


def extension_id(key: str) -> str:
    """Id da extensão carregada sem compactação: fixo pela "key" do manifest (SHA-256 da chave, letras a-p)."""
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def host_manifest(bat_windows_path: str, ext_id: str) -> dict:
    """Manifest do host de native messaging: só a extensão do mcp-vagas pode chamá-lo."""
    return {"name": HOST_NAME, "description": "mcp-vagas: documentos do cofre para a extensão do Chrome",
            "path": bat_windows_path, "type": "stdio", "allowed_origins": [f"chrome-extension://{ext_id}/"]}


def host_bat(distro: str, python: str, env: dict[str, str]) -> str:
    """.bat que o Chrome executa: roda o host no WSL com a cópia estável do servidor."""
    variables = " ".join(f'"{key}={value}"' for key, value in env.items() if key in HOST_ENV_KEYS)
    return (f'@echo off\r\nwsl.exe -d {distro} -e env {variables} "{python}" -m vagas.autofill_host\r\n')


def host_bat_native(python: str, env: dict[str, str]) -> str:
    """.bat que o Chrome executa no Windows nativo: o python.exe da cópia estável, com as variáveis do host."""
    variables = "".join(f'set "{key}={value}"\r\n' for key, value in env.items() if key in HOST_ENV_KEYS)
    return f'@echo off\r\n{variables}"{python}" -m vagas.autofill_host\r\n'


def registry_command(manifest_windows_path: str) -> list[str]:
    return ["reg.exe", "add", f"HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\{HOST_NAME}",
            "/ve", "/t", "REG_SZ", "/d", manifest_windows_path, "/f"]


# --- Integração com Windows e WSL ------------------------------------------------------------

def step(message: str) -> None:
    print(f"\n==> {message}")


def fail(message: str) -> None:
    print(f"\nERRO: {message}", file=sys.stderr)
    sys.exit(1)


def windows_paths() -> dict[str, str]:
    if NATIVE_WINDOWS:
        return {"user": os.environ["USERNAME"], "localappdata": os.environ["LOCALAPPDATA"],
                "appdata": os.environ["APPDATA"], "profile": os.environ["USERPROFILE"]}
    if not shutil.which("cmd.exe"):
        fail("cmd.exe não encontrado: rode este script dentro do WSL, com a integração com o Windows ativa.")
    out = subprocess.run(["cmd.exe", "/c", "echo %USERNAME%^|%LOCALAPPDATA%^|%APPDATA%^|%USERPROFILE%"],
                         capture_output=True, text=True, cwd="/mnt/c").stdout.strip().replace("\r", "")
    user, localappdata, appdata, profile = out.split("|")
    return {"user": user, "localappdata": _wsl_path(localappdata), "appdata": _wsl_path(appdata),
            "profile": _wsl_path(profile)}


def _wsl_path(windows_path: str) -> str:
    return subprocess.run(["wslpath", "-u", windows_path], capture_output=True, text=True).stdout.strip()


def update_stable_install(venv: Path = STABLE_VENV) -> Path:
    if not shutil.which("uv"):
        fail("uv não encontrado (https://docs.astral.sh/uv/).")
    python = venv / ("Scripts/python.exe" if NATIVE_WINDOWS else "bin/python")
    if not python.exists():
        subprocess.run(["uv", "venv", "-q", "-p", "3.12", str(venv)], check=True)
    # Extra [linkedin]: leitor do perfil (Playwright + Chromium, compartilhado com o Claude Code).
    subprocess.run(["uv", "pip", "install", "-q", "--reinstall-package", "vagas", "--python", str(python),
                    f"{REPO}[linkedin]"], check=True)
    subprocess.run([str(python), "-m", "playwright", "install", "chromium"], check=True, capture_output=True)
    return python


SMOKE_CODE = ("import asyncio\nfrom vagas.server import build_server\nfrom mcp import Client\n"
              "async def main():\n    async with Client(build_server()) as c:\n"
              "        print(len((await c.list_tools()).tools))\nasyncio.run(main())")


def smoke_test(distro: str | None, python: Path) -> None:
    via = "python.exe" if NATIVE_WINDOWS else "wsl.exe"
    with tempfile.TemporaryDirectory() as tmp:
        if NATIVE_WINDOWS:
            result = subprocess.run([str(python), "-c", SMOKE_CODE], capture_output=True, text=True,
                                    env={**os.environ, "VAGAS_DB": str(Path(tmp) / "teste.db")})
        else:
            result = subprocess.run(
                ["wsl.exe", "-d", distro, "-e", "env", f"VAGAS_DB={tmp}/teste.db", str(python), "-c", SMOKE_CODE],
                capture_output=True, text=True, cwd="/mnt/c",
            )
    tools = result.stdout.strip().splitlines()[-1:] if result.stdout.strip() else []
    if result.returncode != 0 or not tools or not tools[0].isdigit():
        fail(f"o servidor não subiu pelo {via}:\n{result.stderr[-1500:]}")
    print(f"    servidor respondeu pelo {via} com {tools[0]} tools")


def _windows_path(path: Path) -> str:
    if NATIVE_WINDOWS:
        return str(path)
    return subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True).stdout.strip()


def install_extension(localappdata: Path, distro: str | None, python: Path, env: dict[str, str]) -> Path:
    """Copia a extensão para o Windows e registra o host de native messaging no Chrome (HKCU)."""
    base = localappdata / "vagas"
    target = base / "extensao"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(EXTENSION_DIR, target)
    bat = base / "vagas-host.bat"
    content = host_bat_native(str(python), env) if NATIVE_WINDOWS else host_bat(distro, str(python), env)
    bat.write_text(content, encoding="utf-8", newline="")
    key = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))["key"]
    manifest = base / f"{HOST_NAME}.json"
    manifest.write_text(json.dumps(host_manifest(_windows_path(bat), extension_id(key)), indent=2) + "\n",
                        encoding="utf-8")
    done = subprocess.run(registry_command(_windows_path(manifest)), capture_output=True, text=True,
                          cwd=None if NATIVE_WINDOWS else "/mnt/c",
                          encoding="cp850", errors="replace")  # saída do reg.exe na página de código do console
    if done.returncode != 0:
        fail(f"não consegui registrar o host da extensão no Chrome:\n{done.stderr or done.stdout}")
    return target


def close_desktop() -> None:
    # Só processos do Claude Desktop (Microsoft Store ou instalador), nunca o Claude Code nativo.
    script = ("Get-Process claude -ErrorAction SilentlyContinue | "
              "Where-Object { $_.Path -like '*\\WindowsApps\\Claude_*' -or $_.Path -like '*\\AnthropicClaude\\*' } | "
              "Stop-Process -Force")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], cwd=None if NATIVE_WINDOWS else "/mnt/c",
                   check=False)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sem-skill", action="store_true", help="não gera o zip da Skill")
    parser.add_argument("--fechar-desktop", action="store_true", help="fecha o Claude Desktop no fim")
    parser.add_argument("--sem-extensao", action="store_true", help="não instala a extensão do Chrome")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # mantém a ordem com o stderr quando a saída vai para um pipe

    if NATIVE_WINDOWS:
        distro = None
    else:
        distro = os.environ.get("WSL_DISTRO_NAME") or fail(
            "WSL_DISTRO_NAME vazio: rode dentro do WSL (ou, no Windows sem WSL, com py scripts\\instalar_desktop.py).")
    win = windows_paths()
    data_dir = Path(win["localappdata"]) / "vagas"

    step("Atualizando a cópia estável do servidor")
    python = update_stable_install(data_dir / "venv" if NATIVE_WINDOWS else STABLE_VENV)
    print(f"    {python}")

    step("Registrando o servidor no Claude Desktop")
    config_path = find_config(Path(win["localappdata"]), Path(win["appdata"]))
    if config_path is None:
        fail("claude_desktop_config.json não encontrado. Abra o Claude Desktop uma vez, vá em "
             "Configurações → Desenvolvedor → Editar configuração e rode de novo.")
    if NATIVE_WINDOWS:
        env = native_env(Path.home() / ".claude.json", data_dir, SKILL_DIR)
    else:
        env = desktop_env(Path.home() / ".claude.json", win["user"], Path.home())
    env.update({key: os.environ[key] for key in ENV_KEYS if os.environ.get(key)})
    config = json.loads(config_path.read_text(encoding="utf-8") or "{}")
    merged = (merge_config_native(config, env, str(python)) if NATIVE_WINDOWS
              else merge_config(config, distro, env, str(python)))
    if merged != config:
        backup = config_path.with_name(f"{config_path.name}.bak-{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(config_path, backup)
        config_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"    atualizado: {config_path}\n    backup: {backup.name}")
    else:
        print(f"    já estava atualizado: {config_path}")
    for key, value in env.items():
        print(f"    {key}={value}")

    if not NATIVE_WINDOWS:  # no Windows nativo, as variáveis do bloco env já apontam para a Skill
        step("Ligando a política salarial e os critérios de triagem lidos pelo MCP")
        for name in MCP_FILES:
            print(f"    {name}: {link_personal(Path(env['VAGAS_DB']).parent, SKILL_DIR, name)}")

    step("Testando o servidor como o Desktop vai chamá-lo")
    smoke_test(distro, python)

    extension = None
    if not args.sem_extensao:
        step("Instalando a extensão do Chrome (documentos do cofre)")
        extension = install_extension(Path(win["localappdata"]), distro, python, env)
        print(f"    {extension}\n    host registrado: {HOST_NAME}")

    zip_path = None
    if not args.sem_skill:
        step("Gerando o zip da Skill")
        problems = unfilled(SKILL_DIR)
        if problems:
            fail("preencha os arquivos pessoais da Skill antes de gerar o zip:\n  "
                 + "\n  ".join(problems) + f"\n(pasta: {SKILL_DIR})")
        zip_path = Path(win["profile"]) / "Downloads" / "candidaturas.zip"
        build_zip(SKILL_DIR, zip_path)
        print(f"    {zip_path}")
        commands = build_command_zips(COMMANDS_DIR, Path(win["profile"]) / "Downloads" / "vagas-comandos")
        print(f"    comandos: {len(commands)} zips em {commands[0].parent if commands else '-'}")

    if args.fechar_desktop:
        step("Fechando o Claude Desktop")
        close_desktop()

    step("Pronto. Falta você:")
    print(("    1. Abrir o Claude Desktop" if args.fechar_desktop else
           "    1. Fechar o Claude Desktop por completo (inclusive pelo ícone perto do relógio) e abrir de novo"))
    if zip_path:
        windows_zip = _windows_path(zip_path)
        print(f"    2. Em Configurações → Skills, enviar {windows_zip} (substituindo a versão anterior)")
        print("    3. Opcional: enviar também os zips de Downloads\\vagas-comandos (comandos /apply, /search-jobs...),"
              " se o Desktop oferecer comandos de Skills")
    if extension:
        print(f"    Extensão do Chrome: na primeira vez, abra chrome://extensions, ligue o Modo do desenvolvedor,"
              f" clique em Carregar sem compactação e escolha {_windows_path(extension)}. Nas próximas, só clique"
              " em recarregar na extensão (ou reinicie o Chrome).")


if __name__ == "__main__":
    main()
