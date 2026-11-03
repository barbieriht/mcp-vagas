"""Exportação das candidaturas para CSV. Não depende de MCP.

Separador ";" e UTF-8 com BOM: o Excel em português abre direto em colunas e com acentos; o
Google Sheets detecta o formato sozinho.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from vagas.repo import Repo


def default_export_dir(db_path: Path | str | None = None) -> Path:
    from vagas.config import resolve

    return resolve("export_dir", db_path)[0]


def export_csv(repo: Repo, out_dir: Path | str) -> dict[str, Any]:
    """Grava todas as candidaturas (todas as colunas + last_event_at) num CSV novo; nunca sobrescreve."""
    columns = [row[1] for row in repo.conn.execute("PRAGMA table_info(applications)")] + ["last_event_at"]
    applications = repo.list_applications()["applications"]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(repo.now()).strftime("%Y%m%d-%H%M%S")
    path, n = out_dir / f"vagas_{stamp}.csv", 2
    while path.exists():
        path, n = out_dir / f"vagas_{stamp}_{n}.csv", n + 1

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(columns)
        for application in applications:
            writer.writerow([_cell(application.get(column)) for column in columns])
    return {"path": str(path), "rows": len(applications)}


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value
