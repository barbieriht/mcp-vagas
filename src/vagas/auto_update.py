"""Atualização automática: a cada sessão, o servidor puxa o clone do repositório e reinstala a cópia estável.

O servidor roda de uma cópia instalada (o venv na pasta de dados), não do clone; sem isto, cada máquina
ficava na versão do dia em que rodou o instalador. `update` faz, nesta ordem:

1. `git fetch` da `main` no clone e, se ele está na `main`, sem mudanças locais e só atrás da origem,
   `git merge --ff-only`. Clone com trabalho local (outra branch, arquivo editado, commit não publicado)
   nunca é mexido nem reinstalado: o resultado diz o que fazer à mão.
2. Se o commit do clone não é o da cópia instalada (RECORD, gravado também pelos instaladores),
   reinstala com `install` (None numa instalação editável, de desenvolvimento, que já usa o clone).
3. Acrescenta aos arquivos pessoais da Skill (perfil, critérios, política) os campos de primeiro nível
   que os `.example.md` ganharam desde a versão instalada: no perfil com <PREENCHER>, nos critérios e na
   política vazios (vazio vale o padrão, como sem a linha). Valores do usuário nunca mudam, e um campo
   antigo que ele apagou não volta.

Os subprocessos têm stdin fechado e a saída capturada: no stdio, stdin e stdout do servidor são o
protocolo. Não depende de MCP.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vagas import md_fields, system
from vagas.normalize import normalize_text

log = logging.getLogger(__name__)

BRANCH = "main"
RECORD = "instalado.json"  # commit do clone que a cópia estável tem
REPORT = "atualizacao.json"  # último resultado com novidade, até ser contado ao usuário
LOCK = "atualizacao.lock"
LOCK_STALE_SECONDS = 15 * 60
SKILL_DIR = "skill/candidaturas"
MANUAL = "informar manualmente"
# Arquivo pessoal -> valor dos campos novos.
PERSONAL_FILES = {"perfil.md": "<PREENCHER>", "criterios-triagem.md": "", "politica-salarial.md": ""}

Installer = Callable[[Path], None]


class _GitError(Exception):
    pass


def write_record(data_dir: Path | str, commit: str) -> None:
    path = Path(data_dir) / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    md_fields.write_atomic(path, json.dumps({"commit": commit,
                                             "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}))


def read_record(data_dir: Path | str) -> str | None:
    try:
        return json.loads((Path(data_dir) / RECORD).read_text(encoding="utf-8")).get("commit")
    except (OSError, ValueError, AttributeError):
        return None


def update(repo: Path | str, data_dir: Path | str, install: Installer | None) -> dict[str, Any]:
    """{status: em_dia | atualizado | pulado | erro, ...}; nunca levanta exceção."""
    repo, data_dir = Path(repo), Path(data_dir)
    if not (repo / ".git").exists():
        return {"status": "pulado", "reason": f"{repo} não é um clone git: atualize rodando o instalador de novo."}
    if system.find_executable("git") is None:
        return {"status": "pulado", "reason": "git não encontrado: atualize com git pull e o instalador."}
    lock = _acquire(data_dir)
    if lock is None:
        return {"status": "pulado", "reason": "outra sessão está atualizando o MCP agora."}
    try:
        return _update(repo, data_dir, install)
    except (_GitError, OSError, subprocess.SubprocessError) as exc:
        log.warning("atualização automática falhou: %s", exc)
        return {"status": "erro", "reason": f"{exc}. Atualize à mão: git pull no clone e o instalador."}
    finally:
        lock.unlink(missing_ok=True)


def _update(repo: Path, data_dir: Path, install: Installer | None) -> dict[str, Any]:
    start = _git(repo, "rev-parse", "HEAD")
    installed = read_record(data_dir) if install is not None else start
    warning = None
    try:
        _git(repo, "fetch", "-q", "origin", BRANCH, timeout=30)
    except (_GitError, subprocess.TimeoutExpired):
        warning = "sem acesso ao GitHub: verificada só a versão do clone local."
    remote = f"origin/{BRANCH}"
    behind = int(_git(repo, "rev-list", "--count", f"HEAD..{remote}")) if _has(repo, remote) else 0
    blocked = _local_work(repo, remote)
    if blocked and (behind or start != installed):
        news = f"há {behind} atualizações no GitHub" if behind else "a cópia instalada não é a versão do clone"
        return {"status": "pulado", "reason": f"{blocked} e {news}: atualize à mão com git pull na main e o "
                                              "instalador."}
    if behind:
        _git(repo, "merge", "-q", "--ff-only", remote)
    head = _git(repo, "rev-parse", "HEAD")
    if head == installed:
        return {"status": "em_dia", "version": head[:7], **({"warning": warning} if warning else {})}

    if install is not None:
        try:
            install(repo)
        except Exception as exc:  # o instalador roda código de terceiros (uv); qualquer falha vira aviso
            return {"status": "erro", "reason": f"o clone foi atualizado para {head[:7]}, mas a reinstalação "
                                                f"falhou ({exc}). Rode o instalador de novo com o Claude fechado."}
        write_record(data_dir, head)

    base = installed if installed and _has(repo, installed) else start
    result: dict[str, Any] = {"status": "atualizado", "to": head[:7]}
    if base != head:
        result["from"] = base[:7]
    result["actions"] = _actions(_git(repo, "diff", "--name-only", base, head).splitlines() if base != head else [])
    if adjusted := _adjust_personal_files(repo, base):
        result["files_adjusted"] = adjusted
    if warning:
        result["warning"] = warning
    return result


def _git(repo: Path, *args: str, timeout: float = 60) -> str:
    done = subprocess.run([system.find_executable("git") or "git", *args], cwd=repo, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, **system.hidden_window_options())
    if done.returncode != 0:
        raise _GitError(f"git {args[0]}: {done.stderr.strip()[-300:]}")
    return done.stdout.strip()


def _has(repo: Path, ref: str) -> bool:
    try:
        _git(repo, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    except _GitError:
        return False
    return True


def _local_work(repo: Path, remote: str) -> str | None:
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        return f"o clone está na branch {branch}"
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        return "o clone tem arquivos editados"
    if _has(repo, remote) and int(_git(repo, "rev-list", "--count", f"{remote}..HEAD")):
        return "o clone tem commits que não estão no GitHub"
    return None


def _acquire(data_dir: Path) -> Path | None:
    lock = data_dir / LOCK
    data_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime < LOCK_STALE_SECONDS:
                    return None
                lock.unlink()  # sobra de uma sessão que morreu no meio
            except FileNotFoundError:
                pass
    return None


def _actions(changed: list[str]) -> list[str]:
    actions = ["Abra uma conversa nova para usar a versão nova do MCP (esta conversa segue na anterior)."]
    if any(path.startswith("extension/") for path in changed):
        actions.append("A extensão do Chrome mudou: em chrome://extensions, clique em recarregar nela (no Claude "
                       "Desktop, rode antes o instalar_desktop.py, que copia a extensão para o Windows).")
    if any(path.startswith("skill/") and not path.endswith(".example.md") for path in changed):
        actions.append("A Skill mudou: no Claude Code ela já está atualizada; no Claude Desktop, rode o "
                       "instalar_desktop.py e envie de novo o zip da Skill.")
    if any(path.startswith("scripts/") for path in changed):
        actions.append("Os instaladores mudaram: rode-os de novo para aplicar o que eles configuram.")
    return actions


def _top_items(text: str) -> list[md_fields.Item]:
    items = [item for item in md_fields.parse(text) if item.parent is None and not item.label.startswith("<")]
    labels = [_label_key(item.label) for item in items]
    return [item for item in items if labels.count(_label_key(item.label)) == 1]  # repetidos (Faixa) são dados


def _label_key(label: str) -> str:
    return " ".join(normalize_text(label).split())


def _adjust_personal_files(repo: Path, base: str) -> dict[str, list[str]]:
    adjusted = {}
    for name, placeholder in PERSONAL_FILES.items():
        personal = repo / SKILL_DIR / name
        example = personal.with_name(name.replace(".md", ".example.md"))
        if not personal.exists() or not example.exists():
            continue
        try:
            old = _git(repo, "show", f"{base}:{SKILL_DIR}/{example.name}")
        except _GitError:
            old = ""
        known = {_label_key(item.label) for item in md_fields.parse(old)}
        text = personal.read_text(encoding="utf-8")
        new_text = example.read_text(encoding="utf-8")
        added = []
        previous: md_fields.Item | None = None
        for item in _top_items(new_text):
            have = {_label_key(i.label) for i in md_fields.parse(text) if i.parent is None}
            if _label_key(item.label) not in known and _label_key(item.label) not in have:
                value = item.value if _label_key(item.value) == MANUAL else placeholder
                block = [f"- {item.label}:{' ' + value if value else ''}", *_children(new_text, item)]
                text = _insert(text, item, previous, block)
                added.append(item.label)
            previous = item
        if added:
            md_fields.write_atomic(personal, text)
            adjusted[name] = added
            log.info("campos novos em %s: %s", name, ", ".join(added))
    return adjusted


def _children(text: str, item: md_fields.Item) -> list[str]:
    lines = text.splitlines()
    end = item.line + 1
    while end < len(lines) and lines[end].strip() and lines[end][:1] in (" ", "\t"):
        end += 1
    return lines[item.line + 1:end]


def _insert(text: str, item: md_fields.Item, previous: md_fields.Item | None, block: list[str]) -> str:
    """Logo depois do campo que vem antes dele no exemplo, se o arquivo pessoal tem esse campo na mesma
    seção; senão no fim da seção (criada, se faltar)."""
    lines = text.splitlines(keepends=True)
    if previous is not None and previous.section == item.section:
        anchor = next((i for i in md_fields.parse(text)
                       if i.parent is None and _label_key(i.label) == _label_key(previous.label)), None)
        if anchor is not None:
            end = anchor.line + 1
            while end < len(lines) and lines[end].strip() and lines[end][:1] in (" ", "\t"):
                end += 1
            if end == len(lines) and lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines[end:end] = [line + "\n" for line in block]
            return "".join(lines)
    return md_fields.insert_item(text, item.section, "\n".join(block))


def default_installer() -> Installer | None:
    """Reinstala com o uv no Python deste servidor (o venv da cópia estável). None numa instalação
    editável: o código já é o do clone."""
    package = Path(__file__).resolve().parent
    if package.parent.name == "src" and (package.parents[1] / "pyproject.toml").exists():
        return None

    def install(repo: Path) -> None:
        uv = system.find_executable("uv")
        if uv is None:
            raise RuntimeError("uv não encontrado")
        done = subprocess.run([uv, "pip", "install", "-q", "--reinstall-package", "vagas", "--python", sys.executable,
                               f"{repo}[linkedin]"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=600, **system.hidden_window_options())
        if done.returncode != 0:
            raise RuntimeError(done.stderr.strip()[-500:] or f"uv saiu com código {done.returncode}")

    return install


def find_repo(db_path: Path | str | None = None) -> Path | None:
    """O clone de onde a cópia estável foi instalada: VAGAS_REPO, ou dois níveis acima da pasta da Skill
    (skill/candidaturas), que os instaladores ligam ao servidor."""
    if env := os.environ.get("VAGAS_REPO"):
        candidates = [Path(env)]
    else:
        from vagas.profile_fields import default_skill_dir
        from vagas.repo import VagasError
        try:
            candidates = [default_skill_dir(db_path).resolve().parents[1]]
        except (VagasError, IndexError, OSError):
            candidates = []
    return next((repo for repo in candidates if (repo / ".git").exists()), None)


class Background:
    """Uma atualização por sessão do servidor, numa thread, sem atrasar a subida do protocolo."""

    def __init__(self, repo: Path, data_dir: Path, install: Installer | None):
        self.repo, self.data_dir, self.install = Path(repo), Path(data_dir), install
        self._thread = threading.Thread(target=self._run, name="vagas-atualizacao", daemon=True)

    def start(self) -> "Background":
        self._thread.start()
        return self

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def _run(self) -> None:
        result = update(self.repo, self.data_dir, self.install)
        log.info("atualização automática: %s", result.get("status"))
        if result["status"] != "em_dia":
            md_fields.write_atomic(self.data_dir / REPORT, json.dumps({**result, "reported": False}, ensure_ascii=False))

    def status(self) -> dict[str, Any] | None:
        """O resultado ainda não contado (desta sessão ou de uma anterior), marcado como contado;
        {"status": "verificando"} enquanto roda; None sem novidade."""
        path = self.data_dir / REPORT
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if saved and not saved.pop("reported", True):
            md_fields.write_atomic(path, json.dumps({**saved, "reported": True}, ensure_ascii=False))
            return saved
        return {"status": "verificando"} if self._thread.is_alive() else None


def start(db_path: Path | str | None = None) -> Callable[[], dict[str, Any] | None] | None:
    """Liga a atualização desta sessão (a menos que auto_update = "nao"); devolve o status para o get_config."""
    from vagas.config import resolve
    if resolve("auto_update", db_path)[0] == "nao":
        return None
    repo = find_repo(db_path)
    if repo is None:
        return None
    install = default_installer()
    # O registro fica ao lado do venv da cópia estável (<pasta de dados>/venv); sem cópia, na pasta de dados.
    data_dir = Path(sys.prefix).parent if install is not None else system.default_data_dir()
    return Background(repo, data_dir, install).start().status
