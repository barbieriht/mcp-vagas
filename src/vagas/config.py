"""Configuração dos caminhos usados em cada tarefa (PDFs de currículo, CSVs, rascunho do currículo geral).

Um arquivo só, `config.toml`, ao lado do banco (ou em VAGAS_CONFIG). Prioridade de cada valor:
variável de ambiente > config.toml > padrão. Não depende de MCP.
"""

import os
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


@dataclass(frozen=True)
class Setting:
    env: str
    kind: str  # "dir" ou "file"
    label: str
    default_name: str | None  # relativo à pasta do banco; None = sem padrão (precisa ser configurado)
    suggested_folder: str | None  # nome da pasta sugerida dentro de Documents


SETTINGS: dict[str, Setting] = {
    "resume_out": Setting("VAGAS_RESUME_OUT", "dir", "Pasta onde os PDFs de currículo são gerados", None, "Curriculos"),
    "export_dir": Setting("VAGAS_EXPORT_DIR", "dir", "Pasta dos CSVs exportados", "exports", "Vagas"),
    "master_resume": Setting("VAGAS_MASTER_RESUME", "file", "Arquivo YAML editável do currículo geral",
                             "curriculo.yaml", None),
}


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


def resolve(key: str, db_path: Path | str | None = None) -> tuple[Path | None, str]:
    """Valor efetivo e origem: "env", "config", "default" ou "unset" (sem padrão e nunca definido)."""
    setting = SETTINGS[key]
    if env := os.environ.get(setting.env):
        return Path(env), "env"
    if value := load(db_path).get(key):
        return Path(value), "config"
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


def describe(db_path: Path | str | None = None) -> dict[str, Any]:
    settings, needs_setup = {}, []
    for key, setting in SETTINGS.items():
        value, source = resolve(key, db_path)
        default = default_value(key, db_path)
        settings[key] = {
            "value": str(value) if value else None, "source": source, "description": setting.label,
            "kind": setting.kind, "default": str(default) if default else None, "env": setting.env,
            "suggestions": suggest_dirs(key),
        }
        if source in ("default", "unset"):
            needs_setup.append(key)
    return {"config_file": str(config_path(db_path)), "settings": settings, "needs_setup": needs_setup}


def normalize_path(value: str) -> Path:
    """Aceita caminhos do Windows (C:\\Users\\...) e "~"; devolve o caminho equivalente no WSL."""
    return wsl_path(value.strip()).expanduser()


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
    path = _validated(key, value, db_path)
    folder = path if SETTINGS[key].kind == "dir" else path.parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if not os.access(folder, os.W_OK):
            raise OSError("sem permissão de escrita")
    except OSError as exc:
        raise VagasError(f"Não consegui usar {folder} ({exc}). Escolha outra pasta.") from exc

    current = load(db_path)
    current[key] = str(path)
    target = config_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Configuração do mcp-vagas: um caminho por tarefa. Edite à mão ou peça ao Claude (set_config).",
             "# Variáveis de ambiente (VAGAS_RESUME_OUT, VAGAS_EXPORT_DIR, VAGAS_MASTER_RESUME) têm prioridade."]
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
