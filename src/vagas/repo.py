"""Operações de dados das candidaturas. Não depende de MCP."""

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from vagas.models import INITIAL_STATUSES, SOURCES, STATUSES, WORK_MODES
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


def _application(row: sqlite3.Row) -> dict[str, Any]:
    application = dict(row)
    for field in ("salary_evaluation", "match_terms"):
        if application.get(field):
            application[field] = json.loads(application[field])
    return application


def _iso_instant(field: str, value: str) -> str:
    """Data ou data e hora ISO, como instante UTC comparável com created_at."""
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise VagasError(f"'{field}' deve ser uma data ISO (ex.: 2026-10-01), recebido {value!r}.") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _check_match_terms(match_terms: dict[str, Any] | None) -> None:
    if match_terms is None:
        return
    valid = (
        isinstance(match_terms, dict)
        and set(match_terms) == {"matched", "missing"}
        and all(isinstance(v, list) and all(isinstance(t, str) for t in v) for v in match_terms.values())
    )
    if not valid:
        raise VagasError(
            "'match_terms' deve ser {\"matched\": [termos], \"missing\": [termos]}, como devolvido por score_job_match."
        )


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
        resume_id: int | None = None,
        search_id: int | None = None,
        match_score: int | None = None,
        match_terms: dict[str, Any] | None = None,
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
        if resume_id is not None:
            self._check_resume(resume_id, application_id=None)
        if search_id is not None and not self.conn.execute(
            "SELECT 1 FROM job_searches WHERE id = ?", (search_id,)
        ).fetchone():
            raise VagasError(f"Busca {search_id} não existe (registre-a com save_job_search).")
        if match_score is not None and not 0 <= match_score <= 100:
            raise VagasError(f"'match_score' deve estar entre 0 e 100 (recebido {match_score}).")
        _check_match_terms(match_terms)

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
                    discard_reason, search_id, match_score, match_terms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (company, normalize_company(company), role, url, url_canonical, source,
                 seniority, work_mode, location, salary_expectation, description, status,
                 pending, discard_reason, search_id, match_score,
                 json.dumps(match_terms, ensure_ascii=False) if match_terms is not None else None, now, now),
            )
            self.conn.execute(
                "INSERT INTO events (application_id, at, from_status, to_status) VALUES (?, ?, NULL, ?)",
                (cursor.lastrowid, now, status),
            )
            if resume_id is not None:
                self._link_resume(resume_id, cursor.lastrowid)
        return {"created": True, "application": self.get(cursor.lastrowid)}

    def update_application(
        self,
        application_id: int,
        status: str | None = None,
        note: str | None = None,
        pending: str | None = None,
        discard_reason: str | None = None,
        resume_id: int | None = None,
    ) -> dict[str, Any]:
        """Muda status, pendência, currículo vinculado e/ou anota. pending="" limpa a pendência.

        Mudança de status ou nota gravam evento; só mudar a pendência não grava.
        """
        current = self.get(application_id)
        if all(v is None for v in (status, note, pending, discard_reason, resume_id)):
            raise VagasError("Nada a atualizar: informe status, note, pending ou resume_id.")
        if resume_id is not None:
            self._check_resume(resume_id, application_id)
        _require_choice("status", status, STATUSES)
        if status is not None and status == current["status"]:
            raise VagasError(f"A candidatura {application_id} já está com status {status!r}.")

        new_status = status or current["status"]
        new_pending = current["pending"] if pending is None else (pending.strip() or None)
        new_reason = current["discard_reason"] if new_status == "descartada" else None
        if discard_reason is not None:
            if status != "descartada":
                raise VagasError("'discard_reason' só pode ser informado ao mudar o status para 'descartada'.")
            new_reason = discard_reason.strip() or None
        if new_status == "pendente_usuario" and new_pending is None:
            raise VagasError("Status 'pendente_usuario' exige 'pending' descrevendo o que falta.")
        if new_status == "descartada" and new_reason is None:
            raise VagasError("Status 'descartada' exige 'discard_reason'.")

        now = self.now()
        with self.conn:
            self.conn.execute(
                """
                UPDATE applications
                SET status = ?, pending = ?, discard_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, new_pending, new_reason, now, application_id),
            )
            if status is not None or note is not None:
                self.conn.execute(
                    "INSERT INTO events (application_id, at, from_status, to_status, note) VALUES (?, ?, ?, ?, ?)",
                    (application_id, now, current["status"], new_status, note),
                )
            if resume_id is not None:
                self._link_resume(resume_id, application_id)
        return self.get(application_id)

    def get_history(self, application_id: int) -> dict[str, Any]:
        resumes = self.conn.execute(
            """
            SELECT id, label, pdf_path, created_at FROM resumes
            WHERE application_id = ? ORDER BY created_at, id
            """,
            (application_id,),
        )
        return {
            "application": self.get(application_id),
            "events": self.events(application_id),
            "resumes": [dict(row) for row in resumes],
        }

    def _check_resume(self, resume_id: int, application_id: int | None) -> None:
        row = self.conn.execute("SELECT application_id FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        if row is None:
            raise VagasError(f"Currículo personalizado {resume_id} não existe.")
        linked = row["application_id"]
        if linked is not None and linked != application_id:
            raise VagasError(
                f"Currículo personalizado {resume_id} já está vinculado à candidatura {linked}; "
                "gere outro currículo para esta vaga."
            )

    def _link_resume(self, resume_id: int, application_id: int) -> None:
        self.conn.execute("UPDATE resumes SET application_id = ? WHERE id = ?", (application_id, resume_id))

    def find_application(self, url: str | None = None, company: str | None = None) -> list[dict[str, Any]]:
        """Por URL (match exato da forma canônica) e/ou por empresa (todas as vagas dela).
        Resultado combinado, sem repetição, mais recentes primeiro."""
        url_canonical = canonical_url(url)
        company_norm = normalize_company(company) if company and company.strip() else None
        if url_canonical is None and company_norm is None:
            raise VagasError("Informe 'url' e/ou 'company' para buscar candidaturas.")
        rows = self.conn.execute(
            """
            SELECT * FROM applications
            WHERE url_canonical = ? OR company_norm = ?
            ORDER BY created_at DESC, id DESC
            """,
            (url_canonical, company_norm),
        )
        return [_application(row) for row in rows]

    def list_applications(
        self,
        status: str | None = None,
        only_pending: bool = False,
        source: str | None = None,
        since: str | None = None,
        stale_days: int | None = None,
    ) -> dict[str, Any]:
        """Candidaturas com os filtros combinados (E), mais recentes primeiro.

        status="a_aplicar" (lista de trabalho) ordena pela aderência (maior primeiro, sem nota por
        último) e depois pelas mais recentes.
        stale_days=N: só "aplicada" cujo último evento é mais antigo que N dias (sem resposta).
        """
        _require_choice("status", status, STATUSES)
        _require_choice("source", source, SOURCES)
        conditions, params = [], []
        if status is not None:
            conditions.append("a.status = ?")
            params.append(status)
        if only_pending:
            conditions.append("a.pending IS NOT NULL")
        if source is not None:
            conditions.append("a.source = ?")
            params.append(source)
        if since is not None:
            conditions.append("a.created_at >= ?")
            params.append(_iso_instant("since", since))
        if stale_days is not None:
            if stale_days < 0:
                raise VagasError("'stale_days' não pode ser negativo.")
            threshold = datetime.fromisoformat(self.now()) - timedelta(days=stale_days)
            conditions.append("a.status = 'aplicada' AND last_event_at < ?")
            params.append(threshold.isoformat(timespec="seconds"))
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        by_match = "a.match_score IS NULL, a.match_score DESC, " if status == "a_aplicar" else ""
        rows = self.conn.execute(
            f"""
            SELECT * FROM (
                SELECT a.*, (SELECT MAX(e.at) FROM events e WHERE e.application_id = a.id) AS last_event_at
                FROM applications a
            ) a
            {where}
            ORDER BY {by_match}a.created_at DESC, a.id DESC
            """,
            params,
        )
        applications = [_application(row) for row in rows]
        return {"applications": applications, "count": len(applications)}

    def get(self, application_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if row is None:
            raise VagasError(f"Candidatura {application_id} não existe.")
        return _application(row)

    def set_match(self, application_id: int, match_score: int | None, match_terms: dict[str, Any]) -> None:
        """Atualiza a aderência gravada (recalculada quando o currículo geral muda). Não gera evento."""
        self.get(application_id)
        if match_score is not None and not 0 <= match_score <= 100:
            raise VagasError(f"'match_score' deve estar entre 0 e 100 (recebido {match_score}).")
        _check_match_terms(match_terms)
        with self.conn:
            self.conn.execute(
                "UPDATE applications SET match_score = ?, match_terms = ? WHERE id = ?",
                (match_score, json.dumps(match_terms, ensure_ascii=False), application_id),
            )

    def events(self, application_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE application_id = ? ORDER BY at, id", (application_id,)
        )
        return [dict(row) for row in rows]

    def _by_url(self, url_canonical: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM applications WHERE url_canonical = ?", (url_canonical,)
        ).fetchone()
        return _application(row) if row else None
