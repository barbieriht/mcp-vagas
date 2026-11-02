"""Busca de vagas nos sites por código e sugestão de buscas. Não depende de MCP.

Gupy: a página pública de busca (portal.gupy.io/job-search/term=...) traz os resultados em
__NEXT_DATA__ (props.pageProps.initialJobList), 12 por página, com filtros na própria URL
(city, state, workplaceTypes[], page).
LinkedIn: o endpoint público para visitantes (jobs-guest/.../seeMoreJobPostings/search), sem login,
devolve 10 cartões HTML por página (start=0, 10, ...); filtros f_WT (modalidade) e f_TPR (data).
O filtro de modalidade do LinkedIn não é confiável, então os resultados saem sem modalidade.
Mesmo acesso da leitura de vagas: User-Agent honesto e intervalo mínimo por site (LinkedIn mais
espaçado); bloqueio ou limite vira erro, sem contorno.
"""

import html
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from vagas.job_posting import Fetcher, JobPostingError, http_fetch, parse_salary_text
from vagas.job_search import JobSearchStore
from vagas.models import ROLE_NAMES, WORK_MODES
from vagas.normalize import canonical_url
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore, default_draft_path
from vagas.triage import default_criteria_path, load_criteria

SEARCHABLE = ("gupy", "linkedin")
DEFAULT_PAGES, MAX_PAGES = 2, 5
FILTER_KEYS = {"gupy": ("work_modes", "state", "max_pages"), "linkedin": ("work_modes", "posted", "max_pages")}
SITE_NAMES = {"gupy": "A Gupy", "linkedin": "O LinkedIn"}
POSTED = {"24h": "r86400", "week": "r604800", "month": "r2592000"}
_LINKEDIN_PAGE = 10
_LINKEDIN_MODES = {"presencial": "1", "remoto": "2", "hibrido": "3"}

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TO_GUPY_MODE = {"remoto": "remote", "hibrido": "hybrid", "presencial": "on-site"}
_FROM_GUPY_MODE = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial", "onsite": "presencial"}
_GUPY_CONTRACTS = {"vacancy_type_effective": "clt", "vacancy_type_legal_entity": "pj"}

ROLE_QUERIES = ROLE_NAMES
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


def linkedin_search_url(query: str, location: str | None, filters: dict[str, Any] | None, page: int = 1) -> str:
    filters = filters or {}
    params = {"keywords": query.strip(), "location": (location or "").strip() or "Brazil"}
    if filters.get("work_modes"):
        params["f_WT"] = ",".join(_LINKEDIN_MODES[m] for m in filters["work_modes"])
    if filters.get("posted"):
        params["f_TPR"] = POSTED[filters["posted"]]
    params["start"] = str((page - 1) * _LINKEDIN_PAGE)
    return "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(params)


def _card_text(pattern: str, card: str) -> str | None:
    match = re.search(pattern, card, re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(match.group(1))).split()) or None if match else None


def parse_linkedin_search(page: str) -> list[dict[str, Any]]:
    jobs = []
    for card in page.split("<li")[1:]:
        job_id = re.search(r"urn:li:jobPosting:(\d+)", card)
        if not job_id:
            continue
        salary = _card_text(r'class="[^"]*job-search-card__salary-info[^"]*"[^>]*>(.*?)</span>', card)
        date = re.search(r'job-search-card__listdate[^"]*"[^>]*datetime="([\d-]+)"', card)
        jobs.append({
            "title": _card_text(r'class="[^"]*base-search-card__title[^"]*"[^>]*>(.*?)</h3>', card) or "",
            "company": _card_text(r'class="[^"]*base-search-card__subtitle[^"]*"[^>]*>(.*?)</h4>', card) or "",
            "url": f"https://linkedin.com/jobs/view/{job_id.group(1)}",
            "published_at": date.group(1) if date else None,
            "location": _card_text(r'class="[^"]*job-search-card__location[^"]*"[^>]*>(.*?)</span>', card),
            "work_mode": None,
            "contract": "desconhecido",
            "pcd_flag": None,
            "salary": parse_salary_text(salary) if salary else None,
        })
    return jobs


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
            "salary": None,
        })
    pagination = job_list.get("pagination") or {}
    return jobs, {k: int(pagination.get(k) or 0) for k in ("total", "limit", "offset")}


def _check_filters(source: str, filters: dict[str, Any] | None) -> dict[str, Any]:
    filters = dict(filters or {})
    unknown = [k for k in filters if k not in FILTER_KEYS[source]]
    if unknown:
        raise VagasError(f"Filtro não aceito em {source}: {', '.join(unknown)}. Use: "
                         f"{', '.join(FILTER_KEYS[source])}.")
    if "posted" in filters and filters["posted"] not in POSTED:
        raise VagasError(f"'posted' deve ser um entre: {', '.join(POSTED)}.")
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
        filters = _check_filters(source, filters)
        location = location.strip() if location and location.strip() else None
        previous = self.searches.find_job_search(query, source, location=location)
        if previous["recent"] and not force:
            return {"skipped": True, "previous": previous["search"], "hours_since": previous["hours_since"],
                    "search_id": None, "total": None, "pages_read": 0, "results": []}

        results: list[dict[str, Any]] = []
        total, pages_read = 0, 0
        for number in range(1, filters.get("max_pages", DEFAULT_PAGES) + 1):
            pages_read += 1
            if source == "gupy":
                jobs, pagination = parse_gupy_search(
                    self._fetch(source, gupy_search_url(query, location, filters, number)))
                total = pagination["total"]
                results += jobs
                if not jobs or len(results) >= total:
                    break
            else:
                jobs = parse_linkedin_search(self._fetch(source, linkedin_search_url(query, location, filters, number)))
                results += jobs
                total = len(results)
                if len(jobs) < _LINKEDIN_PAGE:
                    break

        search_id = self.searches.save_job_search(query, source, total, location=location,
                                                  filters=filters or None)["search_id"]
        for job in results:
            known = self.repo.find_application(url=job["url"]) if job["url"] else []
            job["registered"] = {"id": known[0]["id"], "status": known[0]["status"]} if known else None
        return {"skipped": False, "previous": None, "hours_since": None, "search_id": search_id,
                "total": total, "pages_read": pages_read, "results": results}

    def _fetch(self, source: str, url: str) -> str:
        site = SITE_NAMES[source]
        try:
            status, page = self.fetcher(url)
        except JobPostingError as exc:
            raise VagasError(f"{exc} Busque pelo navegador.") from exc
        if status in (429, 999):
            raise VagasError(f"{site} limitou as buscas automáticas por enquanto; espere alguns minutos ou busque "
                             "pelo navegador e registre com save_job_search.")
        if status in (401, 403) or re.search(r"Just a moment|Verify you are human|Blocked - |authwall", page[:5000]):
            raise VagasError(f"{site} bloqueou a busca automática; busque pelo navegador e registre com "
                             "save_job_search.")
        if status != 200:
            raise VagasError(f"{site} respondeu {status} para a busca; busque pelo navegador.")
        return page

    def suggest_job_searches(self) -> dict[str, Any]:
        criteria = load_criteria(self.criteria_path)
        skills, note = self._top_skills()
        searches: list[dict[str, Any]] = []
        for role in criteria.target_roles:
            terms = ROLE_QUERIES[role]
            queries = ([f"{t} {SENIORITY_WORDS[s]}" for t in terms for s in criteria.search_seniorities]
                       or list(terms))
            for source in SEARCHABLE:
                for query in queries:
                    searches.append(self._suggestion(source, query, None, ["remoto"]))
                    searches += [self._suggestion(source, query, city, ["hibrido", "presencial"])
                                 for city in criteria.location_names]
            if skills:
                searches.append(self._suggestion("gupy", f"{terms[-1]} {skills[0].lower()}", None, ["remoto"]))
        return {"searches": searches, "skills": skills, "note": note}

    def _suggestion(self, source: str, query: str, location: str | None, modes: list[str]) -> dict[str, Any]:
        recent = self.searches.find_job_search(query, source, location=location)["recent"]
        filters: dict[str, Any] = {"work_modes": modes}
        if source == "linkedin":  # leituras mais espaçadas: uma página, só vagas da última semana
            filters.update(max_pages=1, posted="week")
        return {"query": query, "source": source, "location": location, "filters": filters, "recent": recent}

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
