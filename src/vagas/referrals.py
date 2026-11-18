"""Indicações: empresas onde alguém indicou o usuário, com quem indicou. Não depende de MCP.

Ficam no banco (tabela referrals), fora da pasta da Skill: e-mail e telefone são de outra pessoa e não vão no zip
da Skill, em log, em evento nem no CSV. A empresa é comparada como em find_application (sem acento, maiúsculas e
sufixo societário) e por palavras inteiras ("Itaú" acha "Itaú Unibanco S.A."). `scope` (opcional) diz para quais
vagas ou áreas a indicação vale: termos separados por vírgula comparados com o cargo da vaga.
"""

import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from vagas.generic_questions import same_company
from vagas.normalize import normalize_company, normalize_text
from vagas.repo import VagasError

FIELDS = ("company", "name", "email", "phone", "role", "scope", "referred_on", "note")
CONTACT = ("email", "phone")  # dados de contato de terceiros: nunca em log, evento ou export
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _clean(field: str, value: Any) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    if not text:
        return None
    if field == "email" and not _EMAIL.fullmatch(text):
        raise VagasError(f"E-mail inválido: {text!r}. Use o formato nome@empresa.com, ou deixe vazio.")
    if field == "phone" and len(re.sub(r"\D", "", text)) < 8:
        raise VagasError("Telefone inválido: informe ao menos 8 dígitos (ex.: +55 11 91234-5678), ou deixe vazio.")
    if field == "referred_on":
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise VagasError(f"Data inválida: {text!r}. Use AAAA-MM-DD (ex.: 2026-11-18).") from None
    return text


def scope_terms(scope: str | None) -> list[str]:
    return [t for t in (normalize_text(p).strip() for p in (scope or "").split(",")) if t]


def fits(referral: dict[str, Any], role: str | None) -> bool:
    """A indicação vale para o cargo: sem scope, para qualquer vaga; com scope, quando um termo aparece no cargo."""
    terms = scope_terms(referral.get("scope"))
    if not terms:
        return True
    words = " ".join(re.findall(r"[a-z0-9]+", normalize_text(role or "")))
    return any(f" {' '.join(re.findall(r'[a-z0-9]+', t))} " in f" {words} " for t in terms)


class ReferralStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {k: row[k] for k in ("id", *FIELDS, "created_at", "updated_at") if row[k] is not None}

    def add(self, company: str, name: str, **fields: Any) -> dict[str, Any]:
        """Cadastra; a mesma pessoa na mesma empresa é atualizada (campo omitido fica, "" limpa).
        Retorna {created, referral}."""
        unknown = set(fields) - set(FIELDS)
        if unknown:
            raise VagasError(f"Campos desconhecidos: {', '.join(sorted(unknown))}.")
        company, name = _clean("company", company), _clean("name", name)
        if not company:
            raise VagasError("Informe 'company': a empresa onde a pessoa trabalha.")
        if not name:
            raise VagasError("Informe 'name': o nome de quem indicou.")
        values = {k: _clean(k, v) for k, v in fields.items() if v is not None}
        norm = normalize_company(company)
        existing = next((r for r in self.conn.execute("SELECT * FROM referrals WHERE company_norm = ?", (norm,))
                         if normalize_text(r["name"]) == normalize_text(name)), None)
        now = self._now()
        if existing is not None:
            changes = {"company": company, "name": name, **values}
            sets = ", ".join(f"{k} = ?" for k in changes)
            self.conn.execute(f"UPDATE referrals SET {sets}, company_norm = ?, updated_at = ? WHERE id = ?",
                              (*changes.values(), norm, now, existing["id"]))
            self.conn.commit()
            return {"created": False, "referral": self.get(existing["id"])}
        row = {"company": company, "name": name, **values}
        cursor = self.conn.execute(
            f"INSERT INTO referrals ({', '.join(row)}, company_norm, created_at, updated_at) "
            f"VALUES ({', '.join('?' for _ in row)}, ?, ?, ?)", (*row.values(), norm, now, now))
        self.conn.commit()
        return {"created": True, "referral": self.get(cursor.lastrowid)}

    def get(self, referral_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM referrals WHERE id = ?", (referral_id,)).fetchone()
        if row is None:
            raise VagasError(f"Indicação {referral_id} não encontrada: confira o id em list_referrals.")
        return self._row(row)

    def entries(self, company: str | None = None) -> list[dict[str, Any]]:
        """Todas, pela empresa; com company, só as dessa empresa (comparada por palavras inteiras)."""
        rows = [self._row(r) for r in self.conn.execute("SELECT * FROM referrals ORDER BY company_norm, name, id")]
        if company and company.strip():
            rows = [r for r in rows if same_company(r["company"], company)]
        return rows

    def remove(self, referral_id: int) -> dict[str, Any]:
        self.get(referral_id)
        self.conn.execute("DELETE FROM referrals WHERE id = ?", (referral_id,))
        self.conn.commit()
        return {"removed": referral_id}

    def for_company(self, company: str | None) -> list[dict[str, Any]]:
        return self.entries(company) if company and company.strip() else []

    def for_application(self, application: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """{fits, other_scope}: as indicações da empresa da vaga que valem para o cargo e as de outra área."""
        found = self.for_company(application.get("company"))
        return {"fits": [r for r in found if fits(r, application.get("role"))],
                "other_scope": [r for r in found if not fits(r, application.get("role"))]}

    def flagged(self, applications: list[dict[str, Any]]) -> set[int]:
        """Os ids das candidaturas com indicação válida para o cargo (uma consulta só)."""
        referrals = self.entries()
        return {a["id"] for a in applications
                if any(same_company(r["company"], a.get("company") or "") and fits(r, a.get("role"))
                       for r in referrals)}
