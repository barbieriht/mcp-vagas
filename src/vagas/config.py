"""Configuração do MCP: caminhos de cada tarefa (PDFs de currículo, CSVs, rascunho do currículo geral)
e o login padrão nos sites de vagas (LinkedIn ou Google, e com qual e-mail).

Um arquivo só, `config.toml`, ao lado do banco (ou em VAGAS_CONFIG). Prioridade de cada valor:
variável de ambiente > config.toml > padrão. Não depende de MCP.
"""

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vagas.db import default_db_path
from vagas.repo import VagasError
from vagas.resume_extract import wsl_path

WINDOWS_USERS = Path("/mnt/c/Users")
IGNORED_WINDOWS_USERS = {
    "Public", "Default", "Default User", "All Users", "desktop.ini", "TEMP", "WsiAccount",  # inglês
    "Público", "Usuário Padrão", "Todos os Usuários",  # português
}


LOGIN_METHODS = ("linkedin", "google")
_LOGIN_ALIASES = {"linkedin": "linkedin", "linked in": "linkedin", "google": "google", "gmail": "google",
                  "conta google": "google"}


@dataclass(frozen=True)
class Setting:
    env: str
    kind: str  # "dir", "file", "choice" ou "text"
    label: str
    default_name: str | None = None  # relativo à pasta do banco; None = sem padrão (precisa ser configurado)
    suggested_folder: str | None = None  # nome da pasta sugerida dentro de Documents
    choices: tuple[str, ...] = ()  # só para kind "choice"


SETTINGS: dict[str, Setting] = {
    "resume_out": Setting("VAGAS_RESUME_OUT", "dir", "Pasta onde os PDFs de currículo são gerados", None, "Curriculos"),
    "export_dir": Setting("VAGAS_EXPORT_DIR", "dir", "Pasta dos CSVs exportados", "exports", "Vagas"),
    "master_resume": Setting("VAGAS_MASTER_RESUME", "file", "Arquivo YAML editável do currículo geral",
                             "curriculo.yaml", None),
    "login_method": Setting("VAGAS_LOGIN_METHOD", "choice", "Como entrar nos sites de vagas: pela conta do LinkedIn "
                            "ou pela conta Google", choices=LOGIN_METHODS),
    "login_email": Setting("VAGAS_LOGIN_EMAIL", "text", "E-mail da conta Google usada para entrar "
                           "(só vale com login_method = google)"),
}
PATH_KINDS = ("dir", "file")


def config_path(db_path: Path | str | None = None) -> Path:
    if env := os.environ.get("VAGAS_CONFIG"):
        return Path(env)
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / "config.toml"


def load(db_path: Path | str | None = None) -> dict[str, str]:
    path = config_path(db_path)
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise VagasError(f"Não consegui ler {path} ({exc}). Corrija o arquivo (linhas `chave = \"valor\"`) "
                         "ou apague-o para configurar de novo.") from exc
    return {key: value for key, value in data.items() if key in SETTINGS and isinstance(value, str) and value}


def default_value(key: str, db_path: Path | str | None = None) -> Path | None:
    name = SETTINGS[key].default_name
    if name is None:
        return None
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / name


def _as_value(key: str, raw: str) -> Path | str:
    if SETTINGS[key].kind in PATH_KINDS:
        return Path(raw)
    return _clean_choice(key, raw) or raw.strip()


def resolve(key: str, db_path: Path | str | None = None) -> tuple[Path | str | None, str]:
    """Valor efetivo e origem: "env", "config", "default" ou "unset" (sem padrão e nunca definido).
    Pastas e arquivos voltam como Path; login_method e login_email, como texto."""
    setting = SETTINGS[key]
    if env := os.environ.get(setting.env):
        return _as_value(key, env), "env"
    if value := load(db_path).get(key):
        return _as_value(key, value), "config"
    default = default_value(key, db_path)
    return (default, "default") if default is not None else (None, "unset")


def _is_real_user(folder: Path) -> bool:
    return folder.name not in IGNORED_WINDOWS_USERS and not folder.name.lower().startswith("defaultuser")


def suggest_dirs(key: str, users_root: Path = WINDOWS_USERS, home: Path | None = None) -> list[str]:
    """Pastas candidatas: Documents do Windows (no WSL) primeiro, depois a home do Linux."""
    folder = SETTINGS[key].suggested_folder
    if folder is None:
        return []
    found: list[str] = []
    if users_root.is_dir():
        for user in sorted(users_root.iterdir()):
            if _is_real_user(user) and (user / "Documents").is_dir():
                found.append(str(user / "Documents" / folder))
    found.append(str((home or Path.home()) / "Documents" / folder))
    return found


def _needs_answer(key: str, db_path: Path | str | None) -> bool:
    """A conta Google só é perguntada a quem escolheu entrar por ela."""
    if key == "login_email":
        return resolve("login_method", db_path)[0] == "google"
    return True


def describe(db_path: Path | str | None = None) -> dict[str, Any]:
    settings, needs_setup = {}, []
    for key, setting in SETTINGS.items():
        value, source = resolve(key, db_path)
        default = default_value(key, db_path)
        settings[key] = {
            "value": str(value) if value else None, "source": source, "description": setting.label,
            "kind": setting.kind, "default": str(default) if default else None, "env": setting.env,
            "suggestions": suggest_dirs(key), "choices": list(setting.choices),
        }
        if source in ("default", "unset") and _needs_answer(key, db_path):
            needs_setup.append(key)
    return {"config_file": str(config_path(db_path)), "settings": settings, "needs_setup": needs_setup}


def normalize_path(value: str) -> Path:
    """Aceita caminhos do Windows (C:\\Users\\...) e "~"; devolve o caminho equivalente no WSL."""
    return wsl_path(value.strip()).expanduser()


def _clean_choice(key: str, value: str) -> str | None:
    """Tolera maiúscula, espaços e ponto final; devolve a forma guardada, ou None se não reconhecer."""
    text = " ".join(value.strip().rstrip(".").split())
    if key == "login_email":
        return text.lower() if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text) else None
    return _LOGIN_ALIASES.get(text.lower())


def _validated_text(key: str, value: str | None) -> str:
    setting = SETTINGS[key]
    if value is None or not value.strip():
        raise VagasError(f"Informe 'value' para {key}: {setting.label.lower()}.")
    cleaned = _clean_choice(key, value)
    if cleaned is None and key == "login_email":
        raise VagasError(f"{value!r} não parece um e-mail; informe a conta Google completa, como nome@gmail.com.")
    if cleaned is None:
        raise VagasError(f"Valor inválido para {key}: {value!r}. Use {' ou '.join(setting.choices)} "
                         "(\"gmail\" vale como google).")
    return cleaned


def _validated(key: str, value: str | None, db_path: Path | str | None) -> Path:
    setting = SETTINGS[key]
    if value is None or not value.strip():
        default = default_value(key, db_path)
        if default is None:
            raise VagasError(f"Informe 'value' para {key}: {setting.label.lower()}. "
                             f"Sugestões: {', '.join(suggest_dirs(key))}.")
        return default
    path = normalize_path(value)
    if not path.is_absolute():
        raise VagasError(f"Informe um caminho absoluto para {key} (recebido {value!r}); "
                         "no Windows, algo como C:\\Users\\<usuário>\\Documents\\Curriculos.")
    if setting.kind == "file" and path.suffix.lower() not in (".yaml", ".yml"):
        raise VagasError(f"{key} deve ser um arquivo .yaml (recebido {value!r}).")
    return path


def set_value(key: str, value: str | None, db_path: Path | str | None = None) -> dict[str, Any]:
    """Grava a configuração (cria a pasta e confere que dá para escrever). Sem value, confirma o padrão."""
    if key not in SETTINGS:
        raise VagasError(f"Configuração desconhecida: {key!r}. Use uma destas: {', '.join(SETTINGS)}.")
    if SETTINGS[key].kind in PATH_KINDS:
        path = _validated(key, value, db_path)
        folder = path if SETTINGS[key].kind == "dir" else path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not os.access(folder, os.W_OK):
                raise OSError("sem permissão de escrita")
        except OSError as exc:
            raise VagasError(f"Não consegui usar {folder} ({exc}). Escolha outra pasta.") from exc
        stored = str(path)
    else:
        stored = _validated_text(key, value)

    current = load(db_path)
    current[key] = stored
    target = config_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Configuração do mcp-vagas: um caminho por tarefa e o login padrão. Edite à mão ou peça ao Claude (set_config).",
             "# login_method = \"linkedin\" ou \"google\"; login_email = conta Google (quando o login é por Google).",
             "# Variáveis de ambiente (VAGAS_RESUME_OUT, VAGAS_EXPORT_DIR, VAGAS_MASTER_RESUME, VAGAS_LOGIN_METHOD,",
             "# VAGAS_LOGIN_EMAIL) têm prioridade."]
    lines += [f"{name} = {_quote(current[name])}" for name in SETTINGS if name in current]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    effective, source = resolve(key, db_path)
    warnings = []
    if source == "env":
        warnings.append(f"A variável {SETTINGS[key].env} está definida no ambiente do servidor e continua valendo "
                        f"({effective}). O valor foi salvo em {target}, mas só passa a valer sem a variável.")
    return {"key": key, "value": str(effective), "source": source, "config_file": str(target), "warnings": warnings}


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
