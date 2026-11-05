"""Cache de estimativas salariais pesquisadas pelo modelo. Não depende de MCP.

Uma pesquisa (salary_searches) é feita para família de cargo + senioridade + moeda, em nível de
empresa ou de mercado (empresa nula), e tem zero ou mais pontos (salary_points). Pesquisa sem
pontos registra "nada encontrado" e conta como fresca, para não ser repetida antes da validade.
"""

import json
import math
import re
import os
import sqlite3
import statistics
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, model_validator

from vagas.models import (
    CONTRACTS, CURRENCIES, ROLE_KEYS, ROLE_NAMES, SALARY_MODES, SALARY_RULES, SENIORITIES, SENIORITY_LABELS,
    Contract, Period,
)
from vagas.normalize import normalize_company, normalize_text
from vagas.repo import VagasError, _require_choice, _utcnow
from vagas.resume_model import Text, _Model, describe_errors
from vagas.salary_policy import default_policy_path, load_policy

DEFAULT_TTL_DAYS = 90
HOURS_PER_MONTH = 160
CLT_BRL_SALARIES_PER_YEAR = 13.33  # 12 salários + 13º + 1/3 de férias
REEVALUATED_STATUSES = ("a_aplicar", "pendente_usuario")
RULE_LABELS = {
    "teto": "mediana, limitada ao teto da política",
    "meio_termo": "meio-termo entre o seu mínimo e a mediana",
    "percentil_25": "quartil inferior das fontes",
    "ponto_baixo": "mediana do ponto baixo de cada fonte",
}


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


_NO_CITY = {"brasil", "brazil", "remoto", "remote", "latam", "latin america"}


def _short_title(title: str) -> str:
    """Cargo sem sufixos de anúncio ("Cientista de Dados Sênior - Search | REF#1" -> "Cientista de Dados Sênior")."""
    return re.split(r"\s+[|–—-]\s+|\s*\|", title.replace('"', ""))[0].strip()


def _city(location: str | None) -> str | None:
    if not location:
        return None
    first = re.sub(r"^Greater\s+|\s+Area$", "", location.split(",")[0].strip())
    return None if normalize_text(first) in _NO_CITY else first


def research_queries(title: str | None, company: str | None, location: str | None, role_key: str,
                     seniority: str | None, company_scope: bool = True, market_scope: bool = True) -> list[str]:
    """Consultas de pesquisa salarial, da mais específica à mais geral: cargo da vaga + empresa + cidade,
    cargo + empresa, empresa no Levels.fyi, e mercado (família e senioridade) na cidade e no Brasil."""
    pt, en = ROLE_NAMES.get(role_key, (None, None))
    title = _short_title(title) if title else None
    city = _city(location)
    level = SENIORITY_LABELS.get(seniority or "", "")
    company = company.strip() if company and company.strip() and not company.startswith("(") else None
    queries: list[str] = []
    if company and company_scope:
        job = title or " ".join(p for p in (pt, level) if p)
        if city:
            queries.append(f'salário "{job}" {company} {city}')
        queries.append(f'salário "{job}" {company}')
        queries.append(f"{company} {en or job} salary Brazil levels.fyi")
    if market_scope:
        family = " ".join(p for p in (pt or title, level) if p)
        if city:
            queries.append(f"salário {family} {city}")
        queries.append(f"salário {family} Brasil")
    return queries


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


def _point_low(point: dict[str, Any]) -> float:
    """Ponto baixo da fonte: a média publicada ou, sem ela, o mínimo da faixa."""
    for key in ("avg_value", "min_value", "max_value"):
        if point[key] is not None:
            return point[key]
    raise AssertionError("ponto sem valores")


def _base_ask(rule: str, values: list[float], lows: list[float], median: float, lo: float) -> float:
    """Valor da regra antes de limitar ao mínimo e ao teto."""
    if rule == "meio_termo":
        return (lo + median) / 2
    if rule == "percentil_25":
        return statistics.quantiles(values, n=4, method="inclusive")[0] if len(values) > 1 else values[0]
    if rule == "ponto_baixo":
        return statistics.median(lows)
    return median


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
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = _utcnow,
                 policy_path: Path | str | None = None, rule: str = "teto"):
        if rule not in SALARY_RULES:
            raise VagasError(f"Regra de pretensão inválida: {rule!r}. Use uma de: {', '.join(SALARY_RULES)} "
                             "(set_config com a chave salary_rule).")
        self.conn = conn
        self.now = now
        self.rule = rule
        self.policy_path = Path(policy_path) if policy_path is not None else default_policy_path()
        self.ttl = timedelta(days=_ttl_days())

    def save_salary_estimate(
        self,
        role_key: str,
        seniority: str,
        currency: str,
        points: list[Any],
        company: str | None = None,
        note: str | None = None,
        application_id: int | None = None,
    ) -> dict[str, Any]:
        self._check_key(role_key, seniority, currency)
        try:
            validated = [p if isinstance(p, SalaryPoint) else SalaryPoint.model_validate(p) for p in points]
        except ValidationError as exc:
            raise VagasError(describe_errors(exc, "Dados salariais inválidos")) from exc
        if application_id is not None:
            self._require_application(application_id)
            if any(p.source.strip().lower() != "vaga" for p in validated):
                raise VagasError("Pontos vinculados a uma candidatura devem ter source 'vaga' "
                                 "(faixa publicada na própria vaga).")
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
                                           min_value, avg_value, max_value, application_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(cursor.lastrowid, p.source, p.source_url, p.contract, p.period,
                  p.min_value, p.avg_value, p.max_value, application_id) for p in validated],
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
            WHERE role_key = ? AND seniority = ? AND currency = ? AND company_norm IS ? AND discarded_at IS NULL
            ORDER BY searched_at DESC, id DESC
            """,
            (role_key, seniority, currency, company_norm),
        ).fetchall()
        now = datetime.fromisoformat(self.now())
        searches = []
        for row in rows:
            points = [dict(p) for p in self.conn.execute(
                """
                SELECT search_id, source, source_url, contract, period, min_value, avg_value, max_value
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

    def discard_salary_estimate(self, search_id: int, reason: str) -> dict[str, Any]:
        """Descarta uma pesquisa (fonte ruim, dado de outro cargo): ela deixa de contar nas avaliações."""
        row = self.conn.execute("SELECT discarded_at FROM salary_searches WHERE id = ?", (search_id,)).fetchone()
        if row is None:
            raise VagasError(f"Pesquisa salarial {search_id} não existe; os ids vêm em search_id dos pontos "
                             "de find_salary_estimate.")
        if not reason or not reason.strip():
            raise VagasError("Informe 'reason': por que a pesquisa não serve (ex.: matéria jornalística).")
        with self.conn:
            self.conn.execute("UPDATE salary_searches SET discarded_at = ?, discard_reason = ? WHERE id = ?",
                              (self.now(), reason.strip(), search_id))
        return {"search_id": search_id, "discarded": True}

    def reevaluate_applications(self, statuses: tuple[str, ...] = REEVALUATED_STATUSES) -> dict[str, Any]:
        """Refaz a avaliação salarial das candidaturas já avaliadas, com a regra e os dados atuais.

        Usa os parâmetros gravados na avaliação (role_key, senioridade, moeda, regime); avaliações
        antigas, sem eles, os recebem do título, da candidatura e do texto do motivo.
        """
        from vagas.job_posting import classify_role

        rows = self.conn.execute(
            f"SELECT id, company, role, url, seniority, salary_evaluation, salary_ask FROM applications "
            f"WHERE salary_evaluation IS NOT NULL AND status IN ({', '.join('?' * len(statuses))}) ORDER BY id",
            statuses).fetchall()
        changed, errors = [], []
        for row in rows:
            previous = json.loads(row["salary_evaluation"])
            inputs = previous.get("inputs") or {}
            currency = re.search(r"\b(BRL|USD|EUR)\b", previous.get("reason") or "")
            args = {
                "role_key": inputs.get("role_key") or classify_role(row["role"])[0],
                "seniority": inputs.get("seniority") or row["seniority"],
                "currency": inputs.get("currency") or (currency[1] if currency else "BRL"),
                "contract": inputs.get("contract") or previous.get("contract") or "desconhecido",
            }
            company = None if row["company"].startswith("(") else row["company"]
            try:
                result = self.evaluate_salary(**args, company=company, application_id=row["id"])
            except VagasError as exc:
                errors.append({"id": row["id"], "company": row["company"], "error": str(exc)})
                continue
            if result["value_to_inform"] != row["salary_ask"] or result["decision"] != previous.get("decision"):
                changed.append({"id": row["id"], "company": row["company"], "role": row["role"], "url": row["url"],
                                "decision": result["decision"], "salary_market": result["median"],
                                "before": row["salary_ask"], "after": result["value_to_inform"]})
        return {"reevaluated": len(rows) - len(errors), "changed": changed, "errors": errors}

    def evaluate_salary(
        self,
        role_key: str,
        seniority: str,
        currency: str,
        contract: str,
        my_min: float | None = None,
        my_max: float | None = None,
        mode: str | None = None,
        pj_multiplier: float | None = None,
        company: str | None = None,
        application_id: int | None = None,
        work_mode: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        """Decide se a vaga passa na triagem salarial e qual valor informar, no regime da vaga.

        Sem my_min, a faixa vem da política salarial (politica-salarial.md), escolhida por
        work_mode, location e moeda (da candidatura, se não informados); mode e pj_multiplier
        explícitos têm prioridade sobre os da política. my_min/my_max são mensais em CLT; numa vaga
        PJ são multiplicados por pj_multiplier (faixas da política sem "CLT" não são).
        Base: faixa publicada na vaga (application_id) -> dados frescos da empresa -> de mercado ->
        pesquisa de mercado fresca sem dados (aplicar com o mínimo) -> nada fresco (pesquisar).
        Com application_id, a avaliação fica gravada na candidatura.
        """
        app = self._require_application(application_id) if application_id is not None else None
        band, scale_pj = None, True
        if my_min is None:
            work_mode = work_mode or (app or {}).get("work_mode")
            location = location or (app or {}).get("location")
            if not work_mode:
                raise VagasError("Informe 'work_mode' (e 'location' para vagas híbridas ou presenciais) para usar "
                                 "a política salarial, ou 'my_min'/'my_max'.")
            policy = load_policy(self.policy_path)
            band = policy.band_for(work_mode, location, currency)
            my_min, my_max, scale_pj = band.min, band.max, band.clt
            mode = mode or policy.mode
            pj_multiplier = pj_multiplier if pj_multiplier is not None else policy.pj_multiplier
        mode = mode or "minimo"
        result = self._evaluate(role_key, seniority, currency, contract, my_min, my_max, mode,
                                pj_multiplier, company, application_id, scale_pj)
        result["policy"] = {"band": band.label if band else None, "mode": mode, "my_min": my_min,
                            "my_max": my_max, "pj_multiplier": pj_multiplier}
        market_missing = result["decision"] == "pesquisar"
        result["research_queries"] = research_queries(
            (app or {}).get("role"), company or (app or {}).get("company"), location or (app or {}).get("location"),
            role_key, seniority, company_scope=result["needs_research"], market_scope=market_missing,
        ) if result["needs_research"] or market_missing else []
        if application_id is not None:
            inputs = {"role_key": role_key, "seniority": seniority, "currency": currency, "contract": contract}
            record = {**result, "inputs": inputs, "evaluated_at": self.now()}
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE applications SET salary_evaluation = ?, salary_basis = ?, salary_market = ?,
                                            salary_rule = ?, salary_ask = ?
                    WHERE id = ?
                    """,
                    (json.dumps(record, ensure_ascii=False), result["basis"], result["median"], result["rule"],
                     result["value_to_inform"], application_id),
                )
        return result

    def _evaluate(self, role_key, seniority, currency, contract, my_min, my_max, mode, pj_multiplier,
                  company, application_id, scale_pj=True) -> dict[str, Any]:
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

        def factor() -> float:
            if pj_multiplier is None:
                raise VagasError("Informe 'pj_multiplier' (do perfil.md): é necessário para converter entre CLT e PJ.")
            return pj_multiplier

        def to_job(value: float, regime: str) -> float:
            if regime not in ("desconhecido", job):
                value = value * factor() if job == "pj" else value / factor()
            return round(value, 2)

        def fmt(v: float) -> str:
            return f"{currency} {v:,.0f}".replace(",", ".")

        scale = factor() if job == "pj" and scale_pj else 1
        lo = my_min * scale
        hi = None if my_max is None else my_max * scale
        result: dict[str, Any] = {
            "decision": None, "value_to_inform": None, "rule": None, "capped": False, "basis": None,
            "contract": job, "median": None, "range": None, "sources": 0, "confidence": None,
            "needs_research": has_company and not found["fresh_company"], "reason": "",
        }

        def ask(values, lows, median, floor, upper) -> dict[str, Any]:
            """Pretensão pela regra, entre o piso e o teto; o teto (máximo da política) não exclui a vaga."""
            base = _base_ask(self.rule, values, lows, median, lo)
            capped = hi is not None and base > hi
            if upper is not None and floor > upper:
                floor = lo
            value = _round_within(base, floor, upper)
            note = f"pretensão pela regra {self.rule} ({RULE_LABELS[self.rule]}): {fmt(value)}"
            if capped:
                note += f", limitada ao teto de {fmt(hi)} da política (o teto não exclui a vaga)"
            return {"value_to_inform": value, "rule": self.rule, "capped": capped, "note": note}

        published = self._published_range(application_id, currency) if application_id is not None else None
        if published is not None:
            raw = [published[k] for k in ("min_value", "avg_value", "max_value") if published[k] is not None]
            vmin, vmax = (to_job(monthly(v, published["period"], published["contract"], currency), published["contract"])
                          for v in (min(raw), max(raw)))
            result.update(basis="vaga", median=round((vmin + vmax) / 2, 2), range=[vmin, vmax], sources=1,
                          confidence="alta", needs_research=False)
            if vmax < lo:
                return {**result, "decision": "nao_aplicar",
                        "reason": f"Teto da faixa publicada na vaga {fmt(vmax)} abaixo do seu mínimo {fmt(lo)} "
                                  f"({job.upper()})."}
            if mode == "faixa" and vmin > hi:
                return {**result, "decision": "nao_aplicar",
                        "reason": f"Piso da faixa publicada na vaga {fmt(vmin)} acima da sua faixa, máximo "
                                  f"{fmt(hi)} ({job.upper()})."}
            chosen = ask([vmin, vmax], [vmin], result["median"], max(lo, vmin), vmax if hi is None else min(vmax, hi))
            note = chosen.pop("note")
            return {**result, **chosen, "decision": "aplicar",
                    "reason": f"Faixa publicada na vaga {fmt(vmin)}–{fmt(vmax)} ({job.upper()}) compatível com seu "
                              f"mínimo {fmt(lo)}; {note}."}

        if has_company and fresh["company"]:
            basis, points = "empresa", fresh["company"]
            result["needs_research"] = False
        elif fresh["market"]:
            basis, points = "mercado", fresh["market"]
        elif found["fresh_market"]:
            value = _round_within(lo, lo, hi)
            return {**result, "decision": "aplicar", "basis": "sem_dados", "value_to_inform": value, "rule": "minimo",
                    "reason": f"Pesquisa recente não encontrou salários para este cargo; aplicar informando "
                              f"seu mínimo, {fmt(value)} ({job.upper()})."}
        else:
            return {**result, "decision": "pesquisar", "needs_research": True,
                    "reason": "Sem dados frescos de salário: pesquise (empresa e mercado) e registre com "
                              "save_salary_estimate antes de avaliar."}

        values = [to_job(p["monthly_value"], p["contract"]) for p in points]
        lows = [to_job(monthly(_point_low(p), p["period"], p["contract"], currency), p["contract"]) for p in points]
        median = round(statistics.median(values), 2)
        sources = len({p["source"].strip().lower() for p in points})
        result.update(basis=basis, median=median, range=[min(values), max(values)],
                      sources=sources, confidence=_confidence(sources))

        where = "da empresa" if basis == "empresa" else "de mercado"
        if median < lo:
            return {**result, "decision": "nao_aplicar",
                    "reason": f"Mediana {where} {fmt(median)} abaixo do seu mínimo {fmt(lo)} ({job.upper()})."}
        if mode == "faixa" and median > hi:
            return {**result, "decision": "nao_aplicar",
                    "reason": f"Mediana {where} {fmt(median)} acima da sua faixa, máximo {fmt(hi)} ({job.upper()})."}
        chosen = ask(values, lows, median, lo, hi)
        note = chosen.pop("note")
        return {**result, **chosen, "decision": "aplicar",
                "reason": f"Mediana {where} {fmt(median)} compatível com seu mínimo {fmt(lo)} ({job.upper()}); "
                          f"{note}."}

    def _published_range(self, application_id: int, currency: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT p.period, p.contract, p.min_value, p.avg_value, p.max_value
            FROM salary_points p JOIN salary_searches s ON s.id = p.search_id
            WHERE p.application_id = ? AND s.currency = ?
            ORDER BY s.searched_at DESC, p.id DESC LIMIT 1
            """,
            (application_id, currency),
        ).fetchone()
        return dict(row) if row else None

    def _require_application(self, application_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT role, company, work_mode, location FROM applications WHERE id = ?",
                                (application_id,)).fetchone()
        if not row:
            raise VagasError(f"Candidatura {application_id} não existe.")
        return dict(row)

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

