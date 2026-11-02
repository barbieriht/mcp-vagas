"""Triagem de uma vaga numa chamada: duplicata, leitura, critérios fixos, aderência, registro e salário.

Não depende de MCP. Os critérios fixos vêm de um arquivo pessoal (criterios-triagem.md), no formato:

    - Cargos alvo: data_scientist, ml_engineer, ai_engineer
    - Cargos condicionados à aderência: data_engineer, data_analyst
    - Aderência mínima: 50
    - Empresas ignoradas: Empresa X, Empresa Y
    - Termos de vaga exclusiva PcD: exclusiva para PcD, vaga afirmativa para PcD
    - Locais aceitos para híbrido e presencial: São Paulo, São Carlos

O que as regras não decidem vira um item em "needs", para a LLM julgar ou pesquisar.
"""

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vagas.db import default_db_path
from vagas.job_posting import Fetcher, JobPostingError, classify_role, http_fetch, read_job_posting
from vagas.models import CURRENCIES, ROLE_KEYS
from vagas.normalize import normalize_company, normalize_text
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore, default_draft_path
from vagas.salary import SalaryStore
from vagas.salary_policy import default_policy_path

_ITEM = re.compile(r"^\s{0,1}[-*]\s+(?P<key>[^:]+?)\s*:\s*(?P<value>.*?)\s*$")
_MODE_LABELS = {"hibrido": "híbrida", "presencial": "presencial"}
_KEYS = {
    "cargos alvo": "target_roles",
    "cargos condicionados a aderencia": "conditional_roles",
    "aderencia minima": "min_match",
    "empresas ignoradas": "ignored_companies",
    "termos de vaga exclusiva pcd": "pcd_terms",
    "locais aceitos para hibrido e presencial": "accepted_locations",
}


@dataclass(frozen=True)
class TriageCriteria:
    target_roles: tuple[str, ...]
    conditional_roles: tuple[str, ...] = ()
    min_match: int = 50
    ignored_companies: tuple[str, ...] = ()  # normalizados como empresa
    pcd_terms: tuple[str, ...] = ()  # normalizados como texto
    accepted_locations: tuple[str, ...] = ()  # normalizados como texto


def default_criteria_path(db_path: Path | str | None = None) -> Path:
    if env := os.environ.get("VAGAS_TRIAGE_CRITERIA"):
        return Path(env)
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / "criterios-triagem.md"


def load_criteria(path: Path | str) -> TriageCriteria:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise VagasError(
            f"Critérios de triagem não encontrados em {path}. Crie o arquivo ou aponte VAGAS_TRIAGE_CRITERIA "
            "para ele (modelo: skill/candidaturas/criterios-triagem.example.md), ou faça a triagem manual."
        ) from None
    return parse_criteria(text, source=path.name)


def _roles(value: str, where: str) -> tuple[str, ...]:
    roles = tuple(r.strip() for r in value.split(",") if r.strip())
    unknown = [r for r in roles if r not in ROLE_KEYS]
    if unknown:
        raise VagasError(f"Cargo desconhecido em {where}: {', '.join(unknown)}. Use valores de role_key: "
                         f"{', '.join(ROLE_KEYS)}.")
    return roles


def parse_criteria(text: str, source: str = "criterios-triagem.md") -> TriageCriteria:
    values: dict[str, Any] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        where = f"{source}, linha {number}"
        if "<PREENCHER" in line:
            raise VagasError(f"Preencha o campo em {where}: {line.strip()}")
        item = _ITEM.match(line)
        if not item or (field := _KEYS.get(normalize_text(item["key"]))) is None:
            continue
        value = item["value"]
        items = [v.strip() for v in value.split(",") if v.strip()]
        if field in ("target_roles", "conditional_roles"):
            values[field] = _roles(value, where)
        elif field == "min_match":
            if not value.isdigit() or not 0 <= int(value) <= 100:
                raise VagasError(f"'Aderência mínima' inválida em {where}: {value!r} (número de 0 a 100).")
            values[field] = int(value)
        elif field == "ignored_companies":
            values[field] = tuple(normalize_company(v) for v in items)
        else:
            values[field] = tuple(normalize_text(v) for v in items)
    if not values.get("target_roles"):
        raise VagasError(f"{source}: informe a linha '- Cargos alvo: data_scientist, ...'.")
    return TriageCriteria(**values)


def _contains(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


class Triage:
    def __init__(
        self,
        conn: sqlite3.Connection,
        fetcher: Fetcher = http_fetch,
        criteria_path: Path | str | None = None,
        policy_path: Path | str | None = None,
        draft_path: Path | str | None = None,
    ):
        self.repo = Repo(conn)
        self.resumes = ResumeStore(conn, draft_path or default_draft_path())
        self.salaries = SalaryStore(conn, policy_path=policy_path or default_policy_path())
        self.fetcher = fetcher
        self.criteria_path = Path(criteria_path) if criteria_path is not None else default_criteria_path()

    def triage_job(self, url: str, search_id: int | None = None, not_duplicate: bool = False) -> dict[str, Any]:
        criteria = load_criteria(self.criteria_path)
        existing = self.repo.find_application(url=url)  # só URL: casa pela forma canônica
        if existing:
            return self._result("ja_registrada", existing[0], None, None, None,
                                [f"Vaga já registrada com status {existing[0]['status']!r}."], [])
        try:
            posting = read_job_posting(url, fetcher=self.fetcher)
        except JobPostingError as exc:
            raise VagasError(f"{exc} Depois, faça a triagem pelos passos manuais da Skill.") from exc

        reasons: list[str] = []
        needs: list[dict[str, Any]] = []
        title, company = posting["title"], posting["company"]
        role_key, seniority = posting["role_key"], posting["seniority"]

        if not not_duplicate:
            similar = self._similar(company, role_key, seniority)
            if similar:
                return self._result("possivel_duplicata", None, posting, None, None, [], [{
                    "kind": "possivel_duplicata",
                    "detail": f"{company} já tem vaga registrada com o mesmo cargo e senioridade, talvez a mesma "
                              "vaga em outra plataforma. Pergunte ao usuário; se for outra vaga, chame triage_job "
                              "de novo com not_duplicate=true.",
                    "matches": similar,
                }])

        discard = self._fixed_criteria(criteria, posting, reasons)
        match = None
        if discard is None:
            match = self._match(posting["description"], needs)
            discard = self._role(criteria, posting, match, reasons, needs)
        if discard is None:
            self._location(criteria, posting, reasons, needs)

        app = self.repo.add_application(
            company=company or "(empresa não informada)", role=title, source=posting["source"], url=url,
            seniority=seniority, work_mode=posting["work_mode"], location=posting["location"],
            description=posting["description"] or None, status="descartada" if discard else "a_aplicar",
            discard_reason=discard, search_id=search_id,
            match_score=match["score"] if match else None,
            match_terms={"matched": match["matched"], "missing": match["missing"]} if match else None,
        )["application"]
        if discard:
            return self._result("descartada", app, posting, match, None, [*reasons, discard], [])

        salary = self._salary(app, posting, needs)
        decision = "a_aplicar"
        if salary and salary["decision"] == "nao_aplicar":
            self.repo.update_application(app["id"], status="descartada", discard_reason=salary["reason"])
            decision = "descartada"
            reasons.append(salary["reason"])
            needs = [n for n in needs if n["kind"] not in ("pesquisa_salarial", "salario")]
        elif salary:
            reasons.append(salary["reason"])
        return self._result(decision, self.repo.get(app["id"]), posting, match, salary, reasons, needs)

    # --- Etapas ---------------------------------------------------------------------------------

    def _similar(self, company: str, role_key: str, seniority: str | None) -> list[dict[str, Any]]:
        if not company:
            return []
        similar = []
        for app in self.repo.find_application(company=company):
            other_role, other_seniority, _ = classify_role(app["role"])
            if (other_role, other_seniority) == (role_key, seniority):
                similar.append({k: app[k] for k in ("id", "company", "role", "source", "url", "status")})
        return similar

    @staticmethod
    def _fixed_criteria(criteria: TriageCriteria, posting: dict[str, Any], reasons: list[str]) -> str | None:
        company = posting["company"] or ""
        if company and normalize_company(company) in criteria.ignored_companies:
            return f"Empresa {company} está na lista de empresas ignoradas."
        text = normalize_text(f"{posting['title']} {posting['description'] or ''}")
        term = next((t for t in criteria.pcd_terms if _contains(text, t)), None)
        if term:
            return f"Vaga exclusiva para PcD (termo {term!r} na vaga)."
        reasons.append("Empresa fora da lista de ignoradas e vaga não exclusiva para PcD.")
        return None

    def _match(self, description: str, needs: list[dict[str, Any]]) -> dict[str, Any] | None:
        try:
            match = self.resumes.score_job_match(description or "")
        except VagasError as exc:
            needs.append({"kind": "aderencia", "detail": f"Aderência não calculada: {exc}"})
            return None
        if match["score"] is None:
            needs.append({"kind": "aderencia", "detail": match["note"]})
        return match

    @staticmethod
    def _role(criteria: TriageCriteria, posting: dict[str, Any], match: dict[str, Any] | None,
              reasons: list[str], needs: list[dict[str, Any]]) -> str | None:
        role_key, title = posting["role_key"], posting["title"]
        if not posting["role_certain"]:
            needs.insert(0, {"kind": "cargo", "detail": (
                f"Cargo {title!r} não reconhecido pelo título. Confirme pela descrição se é um dos cargos alvo "
                f"({', '.join(criteria.target_roles + criteria.conditional_roles)}); se não for, descarte com "
                "update_application. Se for, avalie o salário com evaluate_salary (role_key e senioridade).")})
            return None
        if role_key in criteria.target_roles:
            reasons.append(f"Cargo {role_key} entre os cargos alvo.")
            return None
        if role_key in criteria.conditional_roles:
            score = match["score"] if match else None
            if score is None:
                needs.append({"kind": "aderencia", "detail": (
                    f"Cargo {role_key} só entra com aderência de {criteria.min_match} ou mais, e a aderência não "
                    "foi calculada: julgue pela descrição e descarte com update_application se for baixa.")})
                return None
            if score < criteria.min_match:
                return f"Cargo {role_key} exige aderência de {criteria.min_match} ou mais; aderência {score}."
            reasons.append(f"Cargo {role_key} com aderência {score} (mínimo {criteria.min_match}).")
            return None
        return f"Cargo {role_key} fora dos cargos alvo."

    @staticmethod
    def _location(criteria: TriageCriteria, posting: dict[str, Any], reasons: list[str],
                  needs: list[dict[str, Any]]) -> None:
        mode, location = posting["work_mode"], posting["location"]
        if mode is None:
            needs.append({"kind": "modalidade", "detail": (
                "A página não informa a modalidade (remoto, híbrido, presencial). Confira na vaga e chame "
                "evaluate_salary com work_mode, location e o application_id.")})
            return
        if mode == "remoto":
            reasons.append("Vaga remota.")
            return
        place = normalize_text(location or "")
        accepted = next((c for c in criteria.accepted_locations if _contains(place, c)), None)
        if accepted:
            reasons.append(f"Vaga {_MODE_LABELS[mode]} em local aceito ({location}).")
            return
        needs.append({"kind": "local", "detail": (
            f"Vaga {_MODE_LABELS[mode]} em {location or 'local não informado'}, fora dos locais aceitos. Julgue se o "
            "deslocamento é viável; se não for, descarte com update_application.")})

    def _salary(self, app: dict[str, Any], posting: dict[str, Any], needs: list[dict[str, Any]]) -> dict | None:
        role_key, seniority = posting["role_key"], posting["seniority"]
        published = posting.get("salary")
        currency = published["currency"] if published and published.get("currency") in CURRENCIES else "BRL"
        if not posting["role_certain"]:
            return None
        if seniority is None:
            needs.append({"kind": "senioridade", "detail": (
                "Senioridade não identificada pelo título. Defina pela descrição (anos de experiência, "
                "responsabilidades)" + (", registre a faixa publicada com save_salary_estimate (source 'vaga')"
                                        if published else "") +
                " e chame evaluate_salary com o application_id.")})
            return None
        if published:
            self._save_published(app, posting, currency, published, needs)
        if posting["work_mode"] is None:
            return None
        try:
            result = self.salaries.evaluate_salary(role_key, seniority, currency, posting["contract"],
                                                   company=posting["company"] or None, application_id=app["id"])
        except VagasError as exc:
            needs.append({"kind": "salario", "detail": f"Avaliação salarial não feita: {exc}"})
            return None
        if result["decision"] == "pesquisar" or result["needs_research"]:
            scope = "da empresa e de mercado" if result["decision"] == "pesquisar" else "da empresa"
            needs.append({"kind": "pesquisa_salarial", "detail": (
                f"Pesquise salários {scope} ({role_key}, {seniority}, {currency}), registre com "
                "save_salary_estimate e chame evaluate_salary de novo com o application_id.")})
        return result

    def _save_published(self, app, posting, currency, published, needs) -> None:
        if published.get("period") is None:
            needs.append({"kind": "salario", "detail": (
                f"Faixa publicada sem período ({published}); confira na vaga e registre com save_salary_estimate.")})
            return
        try:
            self.salaries.save_salary_estimate(
                posting["role_key"], posting["seniority"], currency, company=posting["company"] or None,
                application_id=app["id"], points=[{
                    "source": "vaga", "source_url": posting["url"], "contract": posting["contract"],
                    "period": published["period"], "min_value": published.get("min_value"),
                    "max_value": published.get("max_value")}])
        except VagasError as exc:
            needs.append({"kind": "salario", "detail": f"Faixa publicada não registrada: {exc}"})

    @staticmethod
    def _result(decision, application, posting, match, salary, reasons, needs) -> dict[str, Any]:
        return {
            "decision": decision,
            "application": application,
            "posting": {k: v for k, v in posting.items() if k != "description"} if posting else None,
            "match": match,
            "salary": salary,
            "reasons": reasons,
            "needs": needs,
        }
