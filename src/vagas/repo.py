"""Operações de dados das candidaturas. Não depende de MCP."""

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from vagas.models import INITIAL_STATUSES, SOURCES, WORK_MODES
from vagas.normalize import canonical_url, normalize_company


class VagasError(ValueError):
    """Erro de uso com mensagem legível, pensada para o modelo corrigir a chamada."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_text(field: str, value: str | None) -> str:
    if not value or not value.strip():
        raise VagasError(f"'{field}' é obrigatório e não pode ser vazio.")
    return value.strip()


def _require_choice(field: str, value: str | None, choices: tuple[str, ...]) -> None:
    if value is not None and value not in choices:
        raise VagasError(f"'{field}' inválido: {value!r}. Valores aceitos: {', '.join(choices)}.")


class Repo:
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = _utcnow):
        self.conn = conn
        self.now = now

    def add_application(
        self,
        company: str,
        role: str,
        source: str,
        url: str | None = None,
        seniority: str | None = None,
        work_mode: str | None = None,
        location: str | None = None,
        salary_expectation: str | None = None,
        description: str | None = None,
        status: str = "aplicada",
        pending: str | None = None,
        discard_reason: str | None = None,
    ) -> dict[str, Any]:
        company = _require_text("company", company)
        role = _require_text("role", role)
        _require_choice("source", source, SOURCES)
        _require_choice("work_mode", work_mode, WORK_MODES)
        _require_choice("status", status, INITIAL_STATUSES)
        if status == "pendente_usuario":
            pending = _require_text("pending", pending)
        if status == "descartada":
            discard_reason = _require_text("discard_reason", discard_reason)
        elif discard_reason is not None:
            raise VagasError("'discard_reason' só pode ser informado com status 'descartada'.")

        url_canonical = canonical_url(url)
        if url_canonical is not None:
            existing = self._by_url(url_canonical)
            if existing is not None:
                return {"created": False, "application": existing}

        now = self.now()
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO applications (
                    company, company_norm, role, url, url_canonical, source, seniority,
                    work_mode, location, salary_expectation, description, status, pending,
                    discard_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (company, normalize_company(company), role, url, url_canonical, source,
                 seniority, work_mode, location, salary_expectation, description, status,
                 pending, discard_reason, now, now),
            )
            self.conn.execute(
                "INSERT INTO events (application_id, at, from_status, to_status) VALUES (?, ?, NULL, ?)",
                (cursor.lastrowid, now, status),
            )
        return {"created": True, "application": self.get(cursor.lastrowid)}

    def find_application(self, url: str | None = None) -> list[dict[str, Any]]:
        url_canonical = canonical_url(url)
        if url_canonical is None:
            raise VagasError("Informe 'url' para buscar uma candidatura.")
        existing = self._by_url(url_canonical)
        return [existing] if existing else []

    def get(self, application_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if row is None:
            raise VagasError(f"Candidatura {application_id} não existe.")
        return dict(row)

    def events(self, application_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE application_id = ? ORDER BY at, id", (application_id,)
        )
        return [dict(row) for row in rows]

    def _by_url(self, url_canonical: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM applications WHERE url_canonical = ?", (url_canonical,)
        ).fetchone()
        return dict(row) if row else None
