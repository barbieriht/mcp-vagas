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

Linux e macOS (fora do WSL): registra também o host de native messaging da extensão do Chrome nos
navegadores instalados (Chrome, Chromium, Edge, Brave). Carregar a extensão continua manual. No WSL
e no Windows, a extensão vai pelo instalar_desktop.py.

No fim, cria o atalho do painel de configuração (.desktop no menu de aplicativos do Linux, .command na
Mesa do macOS, .lnk na Área de Trabalho do Windows) e abre o painel no navegador (--sem-painel evita).
"""

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from instalar_desktop import (  # noqa: E402
    HOST_ENV_KEYS, HOST_NAME, _registered_env, extension_id, host_manifest, panel_bat_native, shortcut_script,
)

NATIVE_WINDOWS = os.name == "nt"
IN_WSL = not NATIVE_WINDOWS and "microsoft" in platform.uname().release.lower()
MACOS = sys.platform == "darwin"
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


_BROWSERS_LINUX = ("google-chrome", "chromium", "microsoft-edge", "BraveSoftware/Brave-Browser")
_BROWSERS_MACOS = ("Google/Chrome", "Chromium", "Microsoft Edge", "BraveSoftware/Brave-Browser")


def browser_host_dirs(home: Path, macos: bool = MACOS) -> list[Path]:
    """Pastas NativeMessagingHosts de cada navegador baseado no Chromium; a primeira é a do Google Chrome."""
    if macos:
        return [home / "Library/Application Support" / name / "NativeMessagingHosts" for name in _BROWSERS_MACOS]
    return [home / ".config" / name / "NativeMessagingHosts" for name in _BROWSERS_LINUX]


def host_script(python: Path, env: dict[str, str]) -> str:
    """Script que o navegador executa: o host com a cópia estável (a sessão já traz o chaveiro)."""
    variables = " ".join(shlex.quote(f"{key}={value}") for key, value in env.items())
    return f"#!/bin/sh\nexec env {variables} {shlex.quote(str(python))} -m vagas.autofill_host\n"


def install_native_host(data: Path, python: Path, home: Path, macos: bool = MACOS,
                        registered: dict[str, str] | None = None) -> list[Path]:
    """Grava o script do host e o manifest nos navegadores instalados (ou no Google Chrome, se nenhum).

    registered: variáveis do registro do MCP no Claude Code; o host usa o mesmo banco e a mesma config."""
    data.mkdir(parents=True, exist_ok=True)
    script = data / "vagas-host.sh"
    env = {"VAGAS_DB": str(data / "vagas.db")}
    env.update({key: value for key, value in (registered or {}).items() if key in HOST_ENV_KEYS})
    script.write_text(host_script(python, env), encoding="utf-8")
    script.chmod(0o755)
    key = json.loads((REPO / "extension" / "manifest.json").read_text(encoding="utf-8"))["key"]
    manifest = json.dumps(host_manifest(str(script), extension_id(key)), indent=2) + "\n"
    folders = browser_host_dirs(home, macos)
    installed = [folder for folder in folders if folder.parent.is_dir()] or folders[:1]
    paths = []
    for folder in installed:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{HOST_NAME}.json").write_text(manifest, encoding="utf-8")
        paths.append(folder / f"{HOST_NAME}.json")
    return paths


PANEL_NAME = "Painel do mcp-vagas"


def panel_env(data: Path, registered: dict[str, str]) -> dict[str, str]:
    """Variáveis do painel: as do registro do MCP no Claude Code (mesmo banco e mesmas pastas)."""
    return {"VAGAS_DB": str(data / "vagas.db"), **registered}


def _desktop_quote(arg: str) -> str:
    """Aspas da especificação Desktop Entry: dentro de aspas duplas, escapar " ` $ \\; e % vira %%."""
    escaped = "".join("\\" + ch if ch in '"`$\\' else ch for ch in arg).replace("%", "%%")
    return f'"{escaped}"'


def panel_shortcut_path(home: Path, macos: bool = MACOS) -> Path:
    if macos:
        return home / "Desktop" / f"{PANEL_NAME}.command"
    return home / ".local/share/applications/mcp-vagas-painel.desktop"


def panel_shortcut(python: Path, env: dict[str, str], macos: bool = MACOS) -> str:
    """Atalho do painel: .command na Mesa do macOS; no Linux, entrada no menu de aplicativos."""
    if macos:
        variables = " ".join(shlex.quote(f"{key}={value}") for key, value in env.items())
        return f"#!/bin/sh\nexec env {variables} {shlex.quote(str(python))} -m vagas.panel\n"
    command = " ".join(_desktop_quote(part) for part in [*(f"{k}={v}" for k, v in env.items()), str(python)])
    return ("[Desktop Entry]\nType=Application\nName=Painel do mcp-vagas\n"
            "Comment=Configuração, vagas e buscas do mcp-vagas no navegador\n"
            f"Exec=env {command} -m vagas.panel\nTerminal=false\nCategories=Office;\n")


def install_panel_shortcut(python: Path, env: dict[str, str], home: Path, macos: bool = MACOS) -> Path:
    path = panel_shortcut_path(home, macos)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(panel_shortcut(python, env, macos), encoding="utf-8")
    path.chmod(0o755)
    return path


def mcp_registered(claude_json: Path) -> bool:
    try:
        return "vagas" in json.loads(claude_json.read_text(encoding="utf-8")).get("mcpServers", {})
    except (OSError, ValueError):
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sem-extensao", action="store_true", help="não registra o host da extensão do Chrome")
    parser.add_argument("--sem-painel", action="store_true", help="não abre o painel de configuração no fim")
    args = parser.parse_args(argv)
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

    if not (NATIVE_WINDOWS or IN_WSL or args.sem_extensao):
        print("\n==> Extensão do Chrome (currículo, termos de uso e documentos do cofre)")
        registered = _registered_env(Path.home() / ".claude.json")
        for manifest in install_native_host(DATA_DIR, STABLE_PYTHON, Path.home(), registered=registered):
            print(f"    host registrado: {manifest}")
        if not shutil.which("secret-tool") and not MACOS:
            print("    sem secret-tool: a extensão anexa o currículo e marca os termos, mas não há cofre para CPF e RG"
                  " (instale o pacote libsecret-tools para usar o chaveiro do sistema)")
        elif MACOS:
            print("    no macOS ainda não há cofre: a extensão anexa o currículo e marca os termos; documentos você digita")
        print(f"    na primeira vez, abra chrome://extensions, ligue o Modo do desenvolvedor, clique em Carregar sem"
              f" compactação e escolha {REPO / 'extension'}. Nas atualizações, clique em recarregar na extensão.")

    print("\n==> Atalho do painel de configuração")
    registered = _registered_env(Path.home() / ".claude.json")
    env = panel_env(DATA_DIR, registered)
    if NATIVE_WINDOWS:
        skill = REPO / "skill" / "candidaturas"
        env = {"VAGAS_SKILL_DIR": str(skill), "VAGAS_SALARY_POLICY": str(skill / "politica-salarial.md"),
               "VAGAS_TRIAGE_CRITERIA": str(skill / "criterios-triagem.md"), **env}
        bat = DATA_DIR / "painel.bat"
        bat.write_text(panel_bat_native(str(STABLE_PYTHON), env), encoding="utf-8", newline="")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", shortcut_script(str(bat))],
                                capture_output=True, text=True)
        print(f"    {result.stdout.strip() or bat}")
    elif IN_WSL:
        print("    no WSL, o atalho na Área de Trabalho do Windows vem do instalar_desktop.py; aqui, abra com:"
              f" {STABLE_PYTHON} -m vagas.panel")
    else:
        print(f"    {install_panel_shortcut(STABLE_PYTHON, env, Path.home())}")
    if not args.sem_painel:
        print("\n==> Abrindo o painel de configuração no navegador")
        subprocess.run([str(STABLE_PYTHON), "-m", "vagas.panel", "--em-segundo-plano"], env={**os.environ, **env},
                       check=False)

    print("\n==> Pronto. Abra uma sessão nova do Claude Code; os comandos aparecem ao digitar /")
    print("    Para configurar pastas, perfil, critérios e currículo depois, use o painel (atalho acima) ou peça ao"
          " Claude o link dele.")


if __name__ == "__main__":
    main()
