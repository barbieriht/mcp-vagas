"""Cache de estimativas salariais pesquisadas pelo modelo. Não depende de MCP.

Uma pesquisa (salary_searches) é feita para família de cargo + senioridade + moeda, em nível de
empresa ou de mercado (empresa nula), e tem zero ou mais pontos (salary_points). Pesquisa sem
pontos registra "nada encontrado" e conta como fresca, para não ser repetida antes da validade.
"""

import os
import sqlite3
import statistics
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from pydantic import Field, ValidationError, model_validator

from vagas.models import CURRENCIES, ROLE_KEYS, SENIORITIES, Contract, Period
from vagas.normalize import normalize_company
from vagas.repo import VagasError, _require_choice, _utcnow
from vagas.resume_model import Text, _Model, describe_errors

DEFAULT_TTL_DAYS = 90
HOURS_PER_MONTH = 160
CLT_BRL_SALARIES_PER_YEAR = 13.33  # 12 salários + 13º + 1/3 de férias


class SalaryPoint(_Model):
    """Um dado salarial encontrado numa fonte. Informe ao menos um entre mínimo, média e máximo."""

    source: Text = Field(description='Ex.: "vaga", "glassdoor", "linkedin", "guia robert half"')
    source_url: Text | None = None
    contract: Contract = "desconhecido"
    period: Period
    min_value: float | None = Field(None, ge=0)
    avg_value: float | None = Field(None, ge=0)
    max_value: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> "SalaryPoint":
        lo, avg, hi = self.min_value, self.avg_value, self.max_value
        if lo is None and avg is None and hi is None:
            raise ValueError("informe ao menos um entre min_value, avg_value e max_value")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"min_value ({lo}) maior que max_value ({hi})")
        if avg is not None and ((lo is not None and avg < lo) or (hi is not None and avg > hi)):
            raise ValueError(f"avg_value ({avg}) fora do intervalo entre min_value e max_value")
        return self


def monthly(value: float, period: str, contract: str, currency: str) -> float:
    if period == "hora":
        value *= HOURS_PER_MONTH
    elif period == "ano":
        value /= CLT_BRL_SALARIES_PER_YEAR if (contract == "clt" and currency == "BRL") else 12
    return round(value, 2)


def _point_value(point: dict[str, Any]) -> float:
    if point["avg_value"] is not None:
        return point["avg_value"]
    present = [v for v in (point["min_value"], point["max_value"]) if v is not None]
    return sum(present) / len(present)


def _confidence(sources: int) -> str | None:
    return {0: None, 1: "baixa", 2: "media"}.get(sources, "alta")


def _ttl_days() -> int:
    env = os.environ.get("VAGAS_SALARY_TTL_DAYS")
    return int(env) if env else DEFAULT_TTL_DAYS


class SalaryStore:
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = _utcnow):
        self.conn = conn
        self.now = now
        self.ttl = timedelta(days=_ttl_days())

    def save_salary_estimate(
        self,
        role_key: str,
        seniority: str,
        currency: str,
        points: list[Any],
        company: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        self._check_key(role_key, seniority, currency)
        try:
            validated = [p if isinstance(p, SalaryPoint) else SalaryPoint.model_validate(p) for p in points]
        except ValidationError as exc:
            raise VagasError(describe_errors(exc, "Dados salariais inválidos")) from exc
        company, company_norm = self._company(company)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO salary_searches (company, company_norm, role_key, seniority, currency, searched_at, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (company, company_norm, role_key, seniority, currency, self.now(), note),
            )
            self.conn.executemany(
                """
                INSERT INTO salary_points (search_id, source, source_url, contract, period,
                                           min_value, avg_value, max_value)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(cursor.lastrowid, p.source, p.source_url, p.contract, p.period,
                  p.min_value, p.avg_value, p.max_value) for p in validated],
            )
        return {"search_id": cursor.lastrowid, "points": len(validated)}

    def find_salary_estimate(
        self, role_key: str, seniority: str, currency: str, company: str | None = None,
    ) -> dict[str, Any]:
        self._check_key(role_key, seniority, currency)
        _, company_norm = self._company(company)
        scopes = [("company", company_norm)] if company_norm else []
        scopes.append(("market", None))

        result: dict[str, Any] = {"company": None, "market": None, "fresh_company": False,
                                  "fresh_market": False, "points": []}
        for scope, norm in scopes:
            searches = self._searches(role_key, seniority, currency, norm)
            fresh = [s for s in searches if s["fresh"]]
            result[f"fresh_{scope}"] = bool(fresh)
            for search in searches:
                result["points"] += [{"scope": scope, **p, "searched_at": search["searched_at"],
                                      "fresh": search["fresh"]} for p in search["points"]]
            if fresh:
                result[scope] = self._summary(fresh)
        return result

    def _searches(self, role_key, seniority, currency, company_norm) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM salary_searches
            WHERE role_key = ? AND seniority = ? AND currency = ? AND company_norm IS ?
            ORDER BY searched_at DESC, id DESC
            """,
            (role_key, seniority, currency, company_norm),
        ).fetchall()
        now = datetime.fromisoformat(self.now())
        searches = []
        for row in rows:
            points = [dict(p) for p in self.conn.execute(
                """
                SELECT source, source_url, contract, period, min_value, avg_value, max_value
                FROM salary_points WHERE search_id = ? ORDER BY id
                """,
                (row["id"],),
            )]
            for p in points:
                p["monthly_value"] = monthly(_point_value(p), p["period"], p["contract"], currency)
            searches.append({
                "searched_at": row["searched_at"],
                "note": row["note"],
                "fresh": now - datetime.fromisoformat(row["searched_at"]) <= self.ttl,
                "points": points,
            })
        return searches

    @staticmethod
    def _summary(searches: list[dict[str, Any]]) -> dict[str, Any]:
        points = [p for s in searches for p in s["points"]]
        values = [p["monthly_value"] for p in points]
        sources = len({p["source"].strip().lower() for p in points})
        return {
            "points": len(points),
            "sources": sources,
            "median": round(statistics.median(values), 2) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "confidence": _confidence(sources),
            "nothing_found": not points,
            "searched_at": searches[0]["searched_at"],
            "notes": [s["note"] for s in searches if s["note"]],
        }

    @staticmethod
    def _check_key(role_key: str, seniority: str, currency: str) -> None:
        _require_choice("role_key", role_key, ROLE_KEYS)
        _require_choice("seniority", seniority, SENIORITIES)
        _require_choice("currency", currency, CURRENCIES)

    @staticmethod
    def _company(company: str | None) -> tuple[str | None, str | None]:
        if company is None or not company.strip():
            return None, None
        return company.strip(), normalize_company(company)

