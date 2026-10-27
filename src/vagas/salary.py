"""Cache de estimativas salariais pesquisadas pelo modelo. Não depende de MCP.

Uma pesquisa (salary_searches) é feita para família de cargo + senioridade + moeda, em nível de
empresa ou de mercado (empresa nula), e tem zero ou mais pontos (salary_points). Pesquisa sem
pontos registra "nada encontrado" e conta como fresca, para não ser repetida antes da validade.
"""

import math
import os
import sqlite3
import statistics
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from pydantic import Field, ValidationError, model_validator

from vagas.models import CONTRACTS, CURRENCIES, ROLE_KEYS, SALARY_MODES, SENIORITIES, Contract, Period
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


def _round_within(value: float, lo: float, hi: float | None) -> int:
    """Limita a [lo, hi] e arredonda para a centena sem sair do intervalo (nunca abaixo de lo)."""
    value = max(value, lo)
    if hi is not None:
        value = min(value, hi)
    rounded = round(value / 100) * 100
    if rounded < lo:
        rounded = math.ceil(lo / 100) * 100
    elif hi is not None and rounded > hi and math.floor(hi / 100) * 100 >= lo:
        rounded = math.floor(hi / 100) * 100
    return int(rounded)


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

    def evaluate_salary(
        self,
        role_key: str,
        seniority: str,
        currency: str,
        contract: str,
        my_min: float,
        my_max: float | None = None,
        mode: str = "minimo",
        pj_multiplier: float | None = None,
        company: str | None = None,
    ) -> dict[str, Any]:
        """Decide se a vaga passa na triagem salarial e qual valor informar, no regime da vaga.

        my_min/my_max são mensais em CLT; numa vaga PJ são multiplicados por pj_multiplier.
        Base: dados frescos da empresa -> de mercado -> pesquisa de mercado fresca sem dados
        (aplicar com o mínimo) -> nada fresco (pesquisar).
        """
        _require_choice("mode", mode, SALARY_MODES)
        _require_choice("contract", contract, CONTRACTS)
        if my_min < 0:
            raise VagasError("'my_min' não pode ser negativo.")
        if my_max is not None and my_max < my_min:
            raise VagasError(f"'my_max' ({my_max}) menor que 'my_min' ({my_min}).")
        if mode == "faixa" and my_max is None:
            raise VagasError("O modo 'faixa' exige 'my_max'.")
        if pj_multiplier is not None and pj_multiplier <= 0:
            raise VagasError("'pj_multiplier' deve ser maior que zero.")

        job = "clt" if contract == "desconhecido" else contract
        found = self.find_salary_estimate(role_key, seniority, currency, company=company)
        has_company = self._company(company)[1] is not None
        fresh = {scope: [p for p in found["points"] if p["scope"] == scope and p["fresh"]]
                 for scope in ("company", "market")}
        needs_company = has_company and not found["fresh_company"]

        def factor() -> float:
            if pj_multiplier is None:
                raise VagasError("Informe 'pj_multiplier' (do perfil.md): é necessário para converter entre CLT e PJ.")
            return pj_multiplier

        lo = my_min * (factor() if job == "pj" else 1)
        hi = None if my_max is None else my_max * (factor() if job == "pj" else 1)

        def fmt(v: float) -> str:
            return f"{currency} {v:,.0f}".replace(",", ".")

        result: dict[str, Any] = {
            "decision": None, "value_to_inform": None, "basis": None, "contract": job, "median": None,
            "range": None, "sources": 0, "confidence": None, "needs_research": needs_company, "reason": "",
        }

        if has_company and fresh["company"]:
            basis, points = "empresa", fresh["company"]
            result["needs_research"] = False
        elif fresh["market"]:
            basis, points = "mercado", fresh["market"]
        elif found["fresh_market"]:
            value = _round_within(lo, lo, hi)
            return {**result, "decision": "aplicar", "basis": "sem_dados", "value_to_inform": value,
                    "reason": f"Pesquisa recente não encontrou salários para este cargo; aplicar informando "
                              f"seu mínimo, {fmt(value)} ({job.upper()})."}
        else:
            return {**result, "decision": "pesquisar", "needs_research": True,
                    "reason": "Sem dados frescos de salário: pesquise (empresa e mercado) e registre com "
                              "save_salary_estimate antes de avaliar."}

        values = []
        for p in points:
            value, regime = p["monthly_value"], p["contract"]
            if regime not in ("desconhecido", job):
                value = value * factor() if job == "pj" else value / factor()
            values.append(value)
        median = round(statistics.median(values), 2)
        sources = len({p["source"].strip().lower() for p in points})
        result.update(basis=basis, median=median, range=[round(min(values), 2), round(max(values), 2)],
                      sources=sources, confidence=_confidence(sources))

        where = "da empresa" if basis == "empresa" else "de mercado"
        if median < lo:
            return {**result, "decision": "nao_aplicar",
                    "reason": f"Mediana {where} {fmt(median)} abaixo do seu mínimo {fmt(lo)} ({job.upper()})."}
        if mode == "faixa" and median > hi:
            return {**result, "decision": "nao_aplicar",
                    "reason": f"Mediana {where} {fmt(median)} acima da sua faixa, máximo {fmt(hi)} ({job.upper()})."}
        value = _round_within(median, lo, hi)
        return {**result, "decision": "aplicar", "value_to_inform": value,
                "reason": f"Mediana {where} {fmt(median)} compatível com seu mínimo {fmt(lo)} ({job.upper()}); "
                          f"informar {fmt(value)}."}

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

