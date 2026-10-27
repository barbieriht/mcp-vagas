"""Ciclo de vida do currículo geral: rascunho em YAML editável, aprovação e versões. Não depende de MCP."""

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from vagas.db import default_db_path
from vagas.repo import VagasError, _utcnow
from vagas.resume_extract import extract_pages, review_draft, wsl_path
from vagas.resume_model import MasterResume, describe_errors
from vagas.resume_render import render_resume
from vagas.resume_tailor import TailoredSelection, resolve


def default_draft_path(db_path: Path | str | None = None) -> Path:
    if env := os.environ.get("VAGAS_MASTER_RESUME"):
        return Path(env)
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / "curriculo.yaml"


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    # Parágrafos longos em bloco dobrado (>-) ficam legíveis e editáveis à mão.
    style = ">" if len(value) > 80 and "\n" not in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _represent_str)


def _to_yaml(data: dict[str, Any]) -> str:
    return yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100)


def _content_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _validate(data: Any) -> MasterResume:
    if isinstance(data, MasterResume):
        return data
    try:
        return MasterResume.model_validate(data)
    except ValidationError as exc:
        raise VagasError(describe_errors(exc)) from exc


class ResumeStore:
    def __init__(self, conn: sqlite3.Connection, draft_path: Path | str, now: Callable[[], str] = _utcnow):
        self.conn = conn
        self.draft_path = Path(draft_path)
        self.now = now

    def save_master_draft(self, resume: Any, overwrite: bool = False) -> dict[str, Any]:
        data = _validate(resume).as_data()
        if self.draft_path.exists() and not overwrite and self._has_unapproved_edits():
            raise VagasError(
                f"O rascunho {self.draft_path} tem alterações que não foram aprovadas nem escritas por "
                "esta tool (provavelmente edições do usuário). Peça ao usuário para aprovar ou descartar "
                "as edições; só use overwrite=true se ele concordar em sobrescrevê-las."
            )
        text = _to_yaml(data)
        self.draft_path.parent.mkdir(parents=True, exist_ok=True)
        self.draft_path.write_text(text, encoding="utf-8")
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO master_draft (id, file_hash, written_at) VALUES (1, ?, ?)",
                (_text_hash(text), self.now()),
            )
        source = self.conn.execute(
            "SELECT path, pages FROM resume_sources ORDER BY extracted_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if source is None:
            return {"path": str(self.draft_path), "reference": None, "review": None}
        review = review_draft(data, "\n".join(json.loads(source["pages"])))
        return {"path": str(self.draft_path), "reference": source["path"], "review": review}

    def extract_resume_text(self, pdf_path: str | Path) -> dict[str, Any]:
        """Extrai o texto do PDF e o guarda como referência para revisar os próximos rascunhos."""
        path = wsl_path(pdf_path)
        pages = extract_pages(path)
        with self.conn:
            self.conn.execute(
                "INSERT INTO resume_sources (path, pages, extracted_at) VALUES (?, ?, ?)",
                (str(path), json.dumps(pages, ensure_ascii=False), self.now()),
            )
        return {"path": str(path), "page_count": len(pages), "pages": pages}

    def approve_master(self) -> dict[str, Any]:
        data = _validate(self._read_draft()).as_data()
        content_hash = _content_hash(data)
        existing = self.conn.execute(
            "SELECT id FROM master_resumes WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            return {"created": False, "version_id": existing["id"], "content_hash": content_hash}
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO master_resumes (content_hash, content, approved_at) VALUES (?, ?, ?)",
                (content_hash, json.dumps(data, ensure_ascii=False), self.now()),
            )
        return {"created": True, "version_id": cursor.lastrowid, "content_hash": content_hash}

    def get_master_resume(self) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM master_resumes ORDER BY approved_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise VagasError(
                "Nenhum currículo geral aprovado. Gere o rascunho com save_master_draft, peça ao "
                "usuário para revisá-lo e, com a aprovação explícita dele, chame approve_master."
            )
        return {
            "version_id": row["id"],
            "content_hash": row["content_hash"],
            "approved_at": row["approved_at"],
            "resume": json.loads(row["content"]),
        }

    def create_tailored_resume(
        self, selection: Any, out_dir: Path | str | None, application_id: int | None = None,
    ) -> dict[str, Any]:
        """Valida a seleção contra o currículo geral, gera o PDF e registra. Nada é gravado se falhar."""
        if application_id is not None and not self.conn.execute(
            "SELECT 1 FROM applications WHERE id = ?", (application_id,)
        ).fetchone():
            raise VagasError(f"Candidatura {application_id} não existe.")
        if not isinstance(selection, TailoredSelection):
            try:
                selection = TailoredSelection.model_validate(selection)
            except ValidationError as exc:
                raise VagasError(describe_errors(exc, "Seleção inválida")) from exc
        master = self.get_master_resume()
        resolved = resolve(master["resume"], selection)
        rendered = render_resume(resolved, out_dir, label=selection.label)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO resumes (
                    master_resume_id, application_id, label, selection, resolved, pdf_path, pages, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (master["version_id"], application_id, selection.label,
                 json.dumps(selection.model_dump(exclude_none=True), ensure_ascii=False),
                 json.dumps(resolved, ensure_ascii=False), rendered["path"], rendered["pages"], self.now()),
            )
        return {"id": cursor.lastrowid, **rendered}

    def list_resumes(self, application_id: int | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, label, pdf_path, pages, master_resume_id, application_id, created_at
            FROM resumes WHERE ? IS NULL OR application_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (application_id, application_id),
        )
        return [dict(row) for row in rows]

    def get_resume(self, resume_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        if row is None:
            raise VagasError(f"Currículo personalizado {resume_id} não existe.")
        resume = dict(row)
        resume["selection"] = json.loads(resume["selection"])
        resume["resolved"] = json.loads(resume["resolved"])
        return resume

    def _read_draft(self) -> Any:
        if not self.draft_path.exists():
            raise VagasError(f"Não há rascunho em {self.draft_path}. Gere um com save_master_draft.")
        try:
            return yaml.safe_load(self.draft_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise VagasError(f"YAML inválido em {self.draft_path}: {exc}") from exc

    def _has_unapproved_edits(self) -> bool:
        text = self.draft_path.read_text(encoding="utf-8")
        written = self.conn.execute("SELECT file_hash FROM master_draft WHERE id = 1").fetchone()
        if written and written["file_hash"] == _text_hash(text):
            return False
        try:
            data = MasterResume.model_validate(yaml.safe_load(text)).as_data()
        except (yaml.YAMLError, ValidationError):
            return True
        approved = self.conn.execute(
            "SELECT 1 FROM master_resumes WHERE content_hash = ?", (_content_hash(data),)
        ).fetchone()
        return approved is None
