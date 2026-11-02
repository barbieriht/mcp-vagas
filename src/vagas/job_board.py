"""Busca de vagas nos sites por código e sugestão de buscas. Não depende de MCP.

Gupy: a página pública de busca (portal.gupy.io/job-search/term=...) traz os resultados em
__NEXT_DATA__ (props.pageProps.initialJobList), 12 por página, com filtros na própria URL
(city, state, workplaceTypes[], page). Mesmo acesso da leitura de vagas: User-Agent honesto e
intervalo mínimo por site; bloqueio vira erro, sem contorno.
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from vagas.job_posting import Fetcher, JobPostingError, http_fetch
from vagas.job_search import JobSearchStore
from vagas.models import WORK_MODES
from vagas.normalize import canonical_url
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore, default_draft_path
from vagas.triage import default_criteria_path, load_criteria

SEARCHABLE = ("gupy",)
DEFAULT_PAGES, MAX_PAGES = 2, 5
FILTER_KEYS = ("work_modes", "state", "max_pages")

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TO_GUPY_MODE = {"remoto": "remote", "hibrido": "hybrid", "presencial": "on-site"}
_FROM_GUPY_MODE = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial", "onsite": "presencial"}
_GUPY_CONTRACTS = {"vacancy_type_effective": "clt", "vacancy_type_legal_entity": "pj"}

ROLE_QUERIES = {
    "data_scientist": ("cientista de dados", "data scientist"),
    "ml_engineer": ("engenheiro de machine learning", "machine learning engineer"),
    "ai_engineer": ("engenheiro de ia", "ai engineer"),
    "data_engineer": ("engenheiro de dados", "data engineer"),
    "data_analyst": ("analista de dados", "data analyst"),
}
SENIORITY_WORDS = {"estagio": "estágio", "junior": "júnior", "pleno": "pleno", "senior": "sênior",
                   "especialista": "especialista"}


# --- Gupy (funções puras) ----------------------------------------------------------------------

def gupy_search_url(query: str, location: str | None, filters: dict[str, Any] | None, page: int = 1) -> str:
    filters = filters or {}
    parts = [f"term={quote(query.strip(), safe='')}"]
    if location:
        parts.append(f"city={quote(location.strip(), safe='')}")
    if filters.get("state"):
        parts.append(f"state={quote(filters['state'].strip(), safe='')}")
    parts += [f"workplaceTypes[]={_TO_GUPY_MODE[m]}" for m in filters.get("work_modes", [])]
    if page > 1:
        parts.append(f"page={page}")
    return "https://portal.gupy.io/job-search/" + "&".join(parts)


def parse_gupy_search(page: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    match = _NEXT_DATA.search(page)
    job_list = None
    if match:
        try:
            job_list = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("initialJobList")
        except ValueError:
            job_list = None
    if not isinstance(job_list, dict) or "data" not in job_list:
        raise VagasError("A página de busca da Gupy mudou de formato (sem a lista de vagas); busque pelo navegador.")
    jobs = []
    for item in job_list["data"]:
        place = ", ".join(p for p in (item.get("city"), item.get("state")) if p)
        jobs.append({
            "title": (item.get("name") or "").strip(),
            "company": (item.get("careerPageName") or "").strip(),
            "url": canonical_url(item.get("jobUrl")) or item.get("jobUrl"),
            "published_at": (item.get("publishedDate") or "")[:10] or None,
            "location": place or None,
            "work_mode": _FROM_GUPY_MODE.get(str(item.get("workplaceType", "")).lower()),
            "contract": _GUPY_CONTRACTS.get(item.get("type"), "desconhecido"),
            "pcd_flag": item.get("disabilities"),
        })
    pagination = job_list.get("pagination") or {}
    return jobs, {k: int(pagination.get(k) or 0) for k in ("total", "limit", "offset")}


def _check_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    filters = dict(filters or {})
    unknown = [k for k in filters if k not in FILTER_KEYS]
    if unknown:
        raise VagasError(f"Filtro desconhecido: {', '.join(unknown)}. Use: {', '.join(FILTER_KEYS)}.")
    modes = filters.get("work_modes", [])
    if not isinstance(modes, list) or any(m not in WORK_MODES for m in modes):
        raise VagasError(f"'work_modes' deve ser uma lista com valores entre: {', '.join(WORK_MODES)}.")
    pages = filters.get("max_pages", DEFAULT_PAGES)
    if not isinstance(pages, int) or not 1 <= pages <= MAX_PAGES:
        raise VagasError(f"'max_pages' deve ser um número de 1 a {MAX_PAGES}.")
    return filters


class JobBoard:
    def __init__(
        self,
        conn: sqlite3.Connection,
        fetcher: Fetcher = http_fetch,
        criteria_path: Path | str | None = None,
        draft_path: Path | str | None = None,
    ):
        self.repo = Repo(conn)
        self.searches = JobSearchStore(conn)
        self.resumes = ResumeStore(conn, draft_path or default_draft_path())
        self.fetcher = fetcher
        self.criteria_path = Path(criteria_path) if criteria_path is not None else default_criteria_path()

    def search_jobs(self, query: str, source: str, location: str | None = None,
                    filters: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
        if source not in SEARCHABLE:
            raise VagasError(f"A busca por código ainda não está disponível para {source!r} (disponível: "
                             f"{', '.join(SEARCHABLE)}). Busque pelo navegador e registre com save_job_search.")
        filters = _check_filters(filters)
        location = location.strip() if location and location.strip() else None
        previous = self.searches.find_job_search(query, source, location=location)
        if previous["recent"] and not force:
            return {"skipped": True, "previous": previous["search"], "hours_since": previous["hours_since"],
                    "search_id": None, "total": None, "pages_read": 0, "results": []}

        results: list[dict[str, Any]] = []
        total, pages_read = 0, 0
        for number in range(1, filters.get("max_pages", DEFAULT_PAGES) + 1):
            jobs, pagination = parse_gupy_search(self._fetch(gupy_search_url(query, location, filters, number)))
            pages_read += 1
            total = pagination["total"]
            results += jobs
            if not jobs or len(results) >= total:
                break

        search_id = self.searches.save_job_search(query, source, total, location=location,
                                                  filters=filters or None)["search_id"]
        for job in results:
            known = self.repo.find_application(url=job["url"]) if job["url"] else []
            job["registered"] = {"id": known[0]["id"], "status": known[0]["status"]} if known else None
        return {"skipped": False, "previous": None, "hours_since": None, "search_id": search_id,
                "total": total, "pages_read": pages_read, "results": results}

    def _fetch(self, url: str) -> str:
        try:
            status, page = self.fetcher(url)
        except JobPostingError as exc:
            raise VagasError(f"{exc} Busque pelo navegador.") from exc
        if status in (401, 403, 429) or re.search(r"Just a moment|Verify you are human|Blocked - ", page[:5000]):
            raise VagasError("A Gupy bloqueou a busca automática; busque pelo navegador e registre com "
                             "save_job_search.")
        if status != 200:
            raise VagasError(f"A Gupy respondeu {status} para a busca; busque pelo navegador.")
        return page

    def suggest_job_searches(self) -> dict[str, Any]:
        criteria = load_criteria(self.criteria_path)
        skills, note = self._top_skills()
        searches: list[dict[str, Any]] = []
        for role in criteria.target_roles:
            terms = ROLE_QUERIES[role]
            queries = ([f"{t} {SENIORITY_WORDS[s]}" for t in terms for s in criteria.search_seniorities]
                       or list(terms))
            for query in queries:
                searches.append(self._suggestion(query, None, ["remoto"]))
                searches += [self._suggestion(query, city, ["hibrido", "presencial"])
                             for city in criteria.location_names]
            if skills:
                searches.append(self._suggestion(f"{terms[-1]} {skills[0].lower()}", None, ["remoto"]))
        return {"searches": searches, "skills": skills, "note": note}

    def _suggestion(self, query: str, location: str | None, modes: list[str]) -> dict[str, Any]:
        recent = self.searches.find_job_search(query, "gupy", location=location)["recent"]
        return {"query": query, "source": "gupy", "location": location, "filters": {"work_modes": modes},
                "recent": recent}

    def _top_skills(self) -> tuple[list[str], str | None]:
        """Até 3 skills do currículo geral mais citadas nas experiências (empate: ordem do currículo)."""
        try:
            master = self.resumes.get_master_resume()["resume"]
        except VagasError:
            return [], "Sem currículo geral aprovado: as buscas usam só os cargos e os locais."
        text = json.dumps(master.get("experience", []), ensure_ascii=False).lower()
        terms = [t for group in master.get("skills", []) for t in group["terms"]]
        count = {t: len(re.findall(rf"(?<!\w){re.escape(t.lower())}(?!\w)", text)) for t in terms}
        ranked = sorted(terms, key=lambda t: -count[t])
        return ranked[:3], None
