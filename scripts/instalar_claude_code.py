#!/usr/bin/env python3
"""Instala ou atualiza a Skill "candidaturas", os comandos (/apply, /search-jobs...) e o MCP "vagas" no Claude Code.

Uso, na raiz do repositório:
    python3 scripts/instalar_claude_code.py

Cria symlinks em ~/.claude/skills apontando para o repositório (uma cópia só, sempre atualizada),
atualiza a cópia estável do servidor e registra o MCP "vagas" no escopo do usuário se ainda não
estiver registrado. Pode ser rodado de novo a qualquer momento.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS_HOME = Path.home() / ".claude" / "skills"
STABLE_PYTHON = Path.home() / ".local/share/vagas/venv/bin/python"


def skill_dirs(repo: Path) -> list[Path]:
    """A Skill principal e um diretório por comando."""
    return [repo / "skill" / "candidaturas", *sorted(p.parent for p in (repo / "skill" / "comandos").glob("*/SKILL.md"))]


def ensure_link(link: Path, target: Path) -> str:
    """Cria ou corrige o symlink; nunca apaga um diretório ou arquivo real."""
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return "ok"
        link.unlink()
        link.symlink_to(target)
        return "atualizado"
    if link.exists():
        raise FileExistsError(f"{link} existe e não é um symlink; mova ou apague-o e rode de novo.")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return "criado"


def mcp_registered(claude_json: Path) -> bool:
    try:
        return "vagas" in json.loads(claude_json.read_text(encoding="utf-8")).get("mcpServers", {})
    except (OSError, ValueError):
        return False


def windows_user() -> str:
    """Usuário do Windows (as pastas em /mnt/c/Users usam esse nome, não o do Linux)."""
    if shutil.which("cmd.exe"):
        out = subprocess.run(["cmd.exe", "/c", "echo %USERNAME%"], capture_output=True, text=True, cwd="/mnt/c")
        if out.stdout.strip():
            return out.stdout.strip()
    return Path.home().name


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    print("==> Skill e comandos em", SKILLS_HOME)
    for directory in skill_dirs(REPO):
        try:
            status = ensure_link(SKILLS_HOME / directory.name, directory)
        except FileExistsError as exc:
            sys.exit(f"ERRO: {exc}")
        label = directory.name if directory.name == "candidaturas" else f"/{directory.name}"
        print(f"    {label}: {status}")

    print("\n==> Cópia estável do servidor")
    if not STABLE_PYTHON.exists():
        subprocess.run(["uv", "venv", "-q", "-p", "3.12", str(STABLE_PYTHON.parents[1])], check=True)
    # Extra [linkedin]: leitor do perfil (Playwright + Chromium).
    subprocess.run(["uv", "pip", "install", "-q", "--reinstall-package", "vagas", "--python", str(STABLE_PYTHON),
                    f"{REPO}[linkedin]"], check=True)
    subprocess.run([str(STABLE_PYTHON), "-m", "playwright", "install", "chromium"], check=True, capture_output=True)
    print(f"    {STABLE_PYTHON} (com o leitor do LinkedIn)")
    if not (Path.home() / ".local/share/vagas/linkedin-browser").exists():
        print(f"    para o leitor do LinkedIn, faça login uma vez: {STABLE_PYTHON} -m vagas.linkedin login")

    print("\n==> MCP \"vagas\" no Claude Code")
    if mcp_registered(Path.home() / ".claude.json"):
        print("    já registrado (mantido como está)")
    elif shutil.which("claude"):
        out = f"/mnt/c/Users/{windows_user()}/Curriculos"
        subprocess.run(["claude", "mcp", "add", "vagas", "--scope", "user",
                        "-e", f"VAGAS_DB={Path.home()}/.local/share/vagas/vagas.db",
                        "-e", f"VAGAS_RESUME_OUT={out}",
                        "--", str(STABLE_PYTHON), "-m", "vagas.server"], check=True)
        print(f"    registrado; PDFs em {out}")
    else:
        print("    CLI 'claude' não encontrado: registre com o comando da seção Claude Code do README")

    print("\n==> Pronto. Abra uma sessão nova do Claude Code; os comandos aparecem ao digitar /")


if __name__ == "__main__":
    main()
