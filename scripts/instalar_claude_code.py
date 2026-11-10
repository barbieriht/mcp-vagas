#!/usr/bin/env python3
"""Instala ou atualiza a Skill "candidaturas", os comandos (/apply, /search-jobs...) e o MCP "vagas" no Claude Code.

Uso, na raiz do repositório:
    python3 scripts/instalar_claude_code.py

Cria links em ~/.claude/skills apontando para o repositório (uma cópia só, sempre atualizada),
atualiza a cópia estável do servidor e registra o MCP "vagas" no escopo do usuário se ainda não
estiver registrado. Pode ser rodado de novo a qualquer momento.

Linux, macOS e WSL: symlinks, e a cópia estável e o banco em ~/.local/share/vagas.
Windows nativo (sem WSL; rode com `py scripts\\instalar_claude_code.py`): junções no lugar dos
symlinks (não exigem privilégio de administrador), a cópia estável e o banco em %LOCALAPPDATA%\vagas,
e o servidor registrado com VAGAS_SKILL_DIR, VAGAS_SALARY_POLICY e VAGAS_TRIAGE_CRITERIA apontando
para a Skill, no lugar dos symlinks ao lado do banco.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

NATIVE_WINDOWS = os.name == "nt"
REPO = Path(__file__).resolve().parents[1]
SKILLS_HOME = Path.home() / ".claude" / "skills"


def data_dir(native_windows: bool = NATIVE_WINDOWS) -> Path:
    """Mesma pasta de vagas.system.default_data_dir (o instalador roda fora do venv e não importa o pacote)."""
    if native_windows:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "vagas"
    return Path.home() / ".local/share/vagas"


def stable_python(data: Path, native_windows: bool = NATIVE_WINDOWS) -> Path:
    return data / "venv" / ("Scripts/python.exe" if native_windows else "bin/python")


DATA_DIR = data_dir()
STABLE_PYTHON = stable_python(DATA_DIR)


def skill_dirs(repo: Path) -> list[Path]:
    """A Skill principal e um diretório por comando."""
    return [repo / "skill" / "candidaturas", *sorted(p.parent for p in (repo / "skill" / "comandos").glob("*/SKILL.md"))]


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def make_link(link: Path, target: Path) -> None:
    """Symlink; no Windows, junção para pastas (symlink lá exige administrador ou modo de desenvolvedor)."""
    if os.name == "nt" and target.is_dir():
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target)


def remove_link(link: Path) -> None:
    """Apaga só o link (a junção sai com rmdir; o conteúdo do destino fica)."""
    if link.is_junction():
        os.rmdir(link)
    else:
        link.unlink()


def ensure_link(link: Path, target: Path) -> str:
    """Cria ou corrige o link; nunca apaga um diretório ou arquivo real."""
    if is_link(link):
        if link.resolve() == target.resolve():
            return "ok"
        remove_link(link)
        make_link(link, target)
        return "atualizado"
    if link.exists():
        raise FileExistsError(f"{link} existe e não é um link; mova ou apague-o e rode de novo.")
    link.parent.mkdir(parents=True, exist_ok=True)
    make_link(link, target)
    return "criado"


PERSONAL_FILES = ("politica-salarial.md", "criterios-triagem.md")


def personal_links(data_dir: Path, repo: Path) -> list[tuple[Path, Path]]:
    """Symlinks ao lado do banco (padrão de VAGAS_SALARY_POLICY e VAGAS_TRIAGE_CRITERIA) para os arquivos da Skill."""
    return [(data_dir / name, repo / "skill" / "candidaturas" / name) for name in PERSONAL_FILES]


def mcp_add_command(python: Path, data: Path, repo: Path, native_windows: bool = NATIVE_WINDOWS) -> list[str]:
    """Registro do MCP no Claude Code. No Windows nativo, variáveis apontam para a Skill (sem symlinks)."""
    env = [f"VAGAS_DB={data / 'vagas.db'}"]
    if native_windows:
        skill = repo / "skill" / "candidaturas"
        env += [f"VAGAS_SKILL_DIR={skill}", f"VAGAS_SALARY_POLICY={skill / 'politica-salarial.md'}",
                f"VAGAS_TRIAGE_CRITERIA={skill / 'criterios-triagem.md'}"]
    return ["claude", "mcp", "add", "vagas", "--scope", "user", *(part for item in env for part in ("-e", item)),
            "--", str(python), "-m", "vagas.server"]


def mcp_registered(claude_json: Path) -> bool:
    try:
        return "vagas" in json.loads(claude_json.read_text(encoding="utf-8")).get("mcpServers", {})
    except (OSError, ValueError):
        return False


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
    if not (DATA_DIR / "linkedin-browser").exists():
        print(f"    para o leitor do LinkedIn, faça login uma vez: {STABLE_PYTHON} -m vagas.linkedin login")

    print("\n==> Política salarial e critérios de triagem lidos pelo MCP")
    for link, target in ([] if NATIVE_WINDOWS else personal_links(DATA_DIR, REPO)):
        try:
            print(f"    {link} -> {target}: {ensure_link(link, target)}")
        except FileExistsError as exc:
            print(f"    AVISO: {exc}")
        if not target.exists():
            print(f"    crie {target} a partir de {target.stem}.example.md")
    if NATIVE_WINDOWS:
        print("    lidos direto da pasta da Skill (VAGAS_SALARY_POLICY e VAGAS_TRIAGE_CRITERIA no registro do MCP)")
        for name in PERSONAL_FILES:
            if not (REPO / "skill" / "candidaturas" / name).exists():
                print(f"    crie {REPO / 'skill' / 'candidaturas' / name} a partir de {Path(name).stem}.example.md")

    print("\n==> MCP \"vagas\" no Claude Code")
    if mcp_registered(Path.home() / ".claude.json"):
        print("    já registrado (mantido como está)")
    elif shutil.which("claude"):
        command = mcp_add_command(STABLE_PYTHON, DATA_DIR, REPO)
        command[0] = shutil.which("claude")  # no Windows pode ser claude.cmd (npm), que o subprocess não acha sozinho
        subprocess.run(command, check=True)
        print("    registrado; no primeiro uso o Claude pergunta as pastas (currículos, CSVs) e grava em config.toml")
    else:
        print("    CLI 'claude' não encontrado: registre com o comando da seção Claude Code do README")

    print("\n==> Pronto. Abra uma sessão nova do Claude Code; os comandos aparecem ao digitar /")


if __name__ == "__main__":
    main()
