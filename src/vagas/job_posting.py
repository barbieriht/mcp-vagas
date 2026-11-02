"""Leitura de uma vaga a partir da URL: dados estruturados da página, sem a LLM transcrever o texto.

Ordem: Gupy (JSON embutido em __NEXT_DATA__) -> schema.org JobPosting em JSON-LD (LinkedIn e muitos
sites de carreira). Sites que bloqueiam leitura automática (Indeed, Glassdoor) viram erro claro, para a
leitura ser feita pela LLM no navegador do usuário. Sem técnicas de disfarce: User-Agent honesto.
"""

import html
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from vagas.normalize import canonical_url

USER_AGENT = "vagas-mcp/0.1 (uso pessoal; leitura de vagas)"
_BLOCKED = re.compile(r"Just a moment|Verify you are human|Blocked - |Access Denied|unusual traffic|cf-chall",
                      re.IGNORECASE)
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_JSON_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_last_request: dict[str, float] = {}

Fetcher = Callable[[str], tuple[int, str]]


class JobPostingError(ValueError):
    """Não foi possível ler a vaga por código; a mensagem diz o motivo e o que fazer."""


# --- Normalização ------------------------------------------------------------------------------

def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


_SENIORITY = [
    ("estagio", r"\b(estagio|estagiari\w*|intern|internship)\b"),
    ("especialista", r"\b(especialista|specialist|staff|principal|lead|lider)\b"),
    ("senior", r"\b(senior|sr)\b"),
    ("pleno", r"\b(pleno|pl|mid)\b"),
    ("junior", r"\b(junior|jr)\b"),
]
_ROLES = [
    ("ml_engineer", r"(machine learning|\bml\b).*(engineer|engenh|\beng\b)|(engineer|engenh|\beng\b).*(machine learning|\bml\b)"
                    r"|\bmle\b|visao computacional|computer vision"),
    ("ai_engineer", r"\b(ai|llm|genai)\b.*engineer|(engenh|desenvolvedor|developer)\w*.*\b(ia|ai|inteligencia artificial)\b"),
    ("data_scientist", r"data scien|cientista (de )?dados|ciencia de dados"),
    ("data_engineer", r"data engineer|engenheir\w*(\(a\))? de dados"),
    ("data_analyst", r"data analyst|analista de (dados|bi)\b|\bbi analyst"),
]


def classify_role(title: str) -> tuple[str, str | None, bool]:
    """Título -> (role_key, senioridade ou None, certeza do role_key)."""
    text = _plain(title)
    seniority = next((level for level, pattern in _SENIORITY if re.search(pattern, text)), None)
    if seniority is None:  # nível numérico no fim do título: "Data Scientist II", "Desenvolvedor IA III"
        level = re.search(r"\b(i{1,3})\s*$", text)
        seniority = {"i": "junior", "ii": "pleno", "iii": "senior"}.get(level.group(1)) if level else None
    role = next((key for key, pattern in _ROLES if re.search(pattern, text)), None)
    return (role or "outro", seniority, role is not None)


class _Text(HTMLParser):
    _BLOCKS = {"p", "li", "br", "div", "ul", "ol", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    parser = _Text()
    parser.feed(html.unescape(fragment))
    return " ".join("".join(parser.parts).split())


def _source(url: str) -> str:
    host = urlsplit(url if "://" in url else f"https://{url}").netloc.lower()
    for name in ("linkedin", "gupy", "indeed", "glassdoor"):
        if name in host:
            return name
    return "outro"


def _base(url: str) -> dict[str, Any]:
    return {"url": url, "url_canonical": canonical_url(url), "source": _source(url)}


def _with_role(job: dict[str, Any], seniority_override: str | None = None) -> dict[str, Any]:
    role_key, seniority, certain = classify_role(job["title"])
    return {**job, "role_key": role_key, "seniority": seniority_override or seniority, "role_certain": certain}


# --- Gupy --------------------------------------------------------------------------------------

_GUPY_MODES = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial", "onsite": "presencial"}
_GUPY_CONTRACTS = {"vacancy_type_effective": "clt", "vacancy_type_legal_entity": "pj"}


def _gupy(url: str, page: str) -> dict[str, Any] | None:
    match = _NEXT_DATA.search(page)
    if not match:
        return None
    job = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("job")
    if not job or not job.get("name"):
        return None
    company = (job.get("careerPage") or {}).get("name") or (job.get("company") or {}).get("name") or ""
    location = ", ".join(p for p in (job.get("addressCity"), job.get("addressState"), job.get("addressCountry")) if p)
    description = "\n\n".join(t for t in (_text(job.get(k)) for k in ("description", "responsibilities", "prerequisites")) if t)
    internship = job.get("jobType") == "vacancy_type_internship"
    result = {
        **_base(url), "title": job["name"], "company": company, "location": location or None,
        "work_mode": _GUPY_MODES.get(str(job.get("workplaceType", "")).lower()),
        "contract": _GUPY_CONTRACTS.get(job.get("jobType"), "desconhecido"),
    }
    result = _with_role(result, "estagio" if internship else None)
    return {**result, "salary": None, "pcd_flag": job.get("handicapped"),
            "published_at": (job.get("publishedAt") or "")[:10] or None, "description": description}


# --- JSON-LD (schema.org JobPosting) -----------------------------------------------------------

_PERIODS = {"HOUR": "hora", "MONTH": "mes", "YEAR": "ano"}


def _job_posting_ld(page: str) -> dict[str, Any] | None:
    for blob in _JSON_LD.findall(page):
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _name(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("name")
    return value or None


def _salary(base: Any) -> dict[str, Any] | None:
    if not isinstance(base, dict):
        return None
    value = base.get("value") or {}
    if not isinstance(value, dict):
        value = {"value": value}
    low = value.get("minValue", value.get("value"))
    high = value.get("maxValue", value.get("value"))
    if low is None and high is None:
        return None
    return {"currency": base.get("currency") or value.get("currency"),
            "period": _PERIODS.get(str(value.get("unitText", "")).upper()), "min_value": low, "max_value": high}


def _jsonld(url: str, page: str) -> dict[str, Any] | None:
    item = _job_posting_ld(page)
    if not item or not item.get("title"):
        return None
    places = item.get("jobLocation") or []
    place = places[0] if isinstance(places, list) and places else places
    address = (place or {}).get("address") or {} if isinstance(place, dict) else {}
    location = ", ".join(p for p in (_name(address.get("addressLocality")), _name(address.get("addressRegion")),
                                     _name(address.get("addressCountry"))) if p)
    employment = item.get("employmentType") or []
    employment = [employment] if isinstance(employment, str) else employment
    result = {
        **_base(url), "title": item["title"], "company": _name(item.get("hiringOrganization")) or "",
        "location": location or None,
        "work_mode": "remoto" if item.get("jobLocationType") == "TELECOMMUTE" else None,
        "contract": "pj" if "CONTRACTOR" in employment else "desconhecido",
    }
    result = _with_role(result, "estagio" if "INTERN" in employment else None)
    return {**result, "salary": _salary(item.get("baseSalary")), "pcd_flag": None,
            "published_at": (item.get("datePosted") or "")[:10] or None, "description": _text(item.get("description"))}


# --- LinkedIn (página pública para visitantes, sem login) ---------------------------------------
# Nem toda página traz JSON-LD; o HTML do cartão do topo, os critérios e a descrição sempre vêm.
# A modalidade não é publicada (só "remoto" no JSON-LD, quando há): é inferida do texto.

_LI_TITLE = re.compile(r'<h[12][^>]*class="[^"]*topcard__title[^"]*"[^>]*>(.*?)</h[12]>', re.S)
_LI_COMPANY = re.compile(r'class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', re.S)
_LI_LOCATION = re.compile(r'class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)</span>', re.S)
_LI_DESCRIPTION = re.compile(r'class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', re.S)
_LI_CRITERIA = re.compile(r'job-criteria-subheader[^>]*>(.*?)</h3>\s*<span[^>]*>(.*?)</span>', re.S)
_LI_SALARY = re.compile(r'class="[^"]*compensation__salary[^"]*"[^>]*>(.*?)</div>', re.S)
_LI_SENIORITY = [("estagio", r"estagio|internship"), ("junior", r"entry level|junior|assistente|assistant")]
_LI_PERIODS = [("mes", r"/\s*(mes|month|mo)\b"), ("ano", r"/\s*(ano|yr|year)\b"), ("hora", r"/\s*(hora|hr|hour|h)\b")]
_REMOTE = r"\b(remot[oa]s?|remote|home office|work from home)\b"
_HYBRID = r"\b(hibrid[oa]s?|hybrid)\b"
_ONSITE = r"\b(presenci\w*|on-?site|in-office)\b"


def infer_work_mode(text: str) -> str | None:
    """Modalidade pelo texto da vaga; None se não houver menção ou se ela for ambígua."""
    text = _plain(text)
    if re.search(_HYBRID, text):
        return "hibrido"
    remote, onsite = re.search(_REMOTE, text), re.search(_ONSITE, text)
    if remote and onsite:
        return None
    return "remoto" if remote else "presencial" if onsite else None


def _amount(text: str) -> float:
    if re.search(r",\d{2}$", text):
        text = text.replace(".", "").replace(",", ".")
    elif re.search(r"\.\d{2}$", text):
        text = text.replace(",", "")
    else:
        text = text.replace(".", "").replace(",", "")
    return float(text)


def parse_salary_text(text: str) -> dict[str, Any] | None:
    """"R$ 8.000,00/mês - R$ 12.000,00/mês" -> {currency, period (ou None), min_value, max_value}."""
    text = " ".join(text.split())
    amounts = [_amount(a) for a in re.findall(r"\d[\d.,]*\d|\d", text)]
    if not amounts:
        return None
    currency = "BRL" if "R$" in text else "EUR" if "€" in text else "USD" if "$" in text else None
    period = next((p for p, pattern in _LI_PERIODS if re.search(pattern, _plain(text))), None)
    return {"currency": currency, "period": period, "min_value": min(amounts), "max_value": max(amounts)}


def _linkedin(url: str, page: str) -> dict[str, Any] | None:
    if _source(url) != "linkedin":
        return None
    ld = _jsonld(url, page)
    title = _LI_TITLE.search(page)
    if not title:
        return ld
    main = page.split("similar-jobs")[0]  # o resto da página são vagas semelhantes, de outras empresas
    found_description = _LI_DESCRIPTION.search(main)
    company, location, salary = _LI_COMPANY.search(main), _LI_LOCATION.search(main), _LI_SALARY.search(main)
    criteria = {_plain(_text(k)): _plain(_text(v)) for k, v in _LI_CRITERIA.findall(main)}
    level = criteria.get("seniority level") or criteria.get("nivel de experiencia") or ""
    employment = criteria.get("employment type") or criteria.get("tipo de emprego") or ""

    result = {**_base(url), "title": _text(title.group(1)),
              "company": _text(company.group(1)) if company else (ld or {}).get("company", ""),
              "location": (_text(location.group(1)) if location else None) or (ld or {}).get("location")}
    role_key, seniority, certain = classify_role(result["title"])
    seniority = seniority or next((s for s, pattern in _LI_SENIORITY if re.search(pattern, level)), None)
    if "estagio" in employment or "internship" in employment:
        seniority = "estagio"
    contract = "pj" if re.search(r"\b(contract|contrato)\b", employment) else "desconhecido"
    description = _text(found_description.group(1)) if found_description else (ld or {}).get("description", "")
    work_mode, inferred = None, False
    if ld:
        contract = ld["contract"] if ld["contract"] != "desconhecido" else contract
        work_mode = ld["work_mode"]
    if work_mode is None:
        work_mode = infer_work_mode(f"{result['title']} {description}")
        inferred = work_mode is not None
    return {**result, "work_mode": work_mode, "work_mode_inferred": inferred, "contract": contract,
            "role_key": role_key, "seniority": seniority, "role_certain": certain,
            "salary": parse_salary_text(_text(salary.group(1))) if salary else (ld or {}).get("salary"),
            "pcd_flag": None, "published_at": (ld or {}).get("published_at"), "description": description}


def extract_job(url: str, page: str) -> dict[str, Any]:
    """HTML da página da vaga -> campos normalizados."""
    for extractor in (_gupy, _linkedin, _jsonld):
        job = extractor(url, page)
        if job:
            return job
    raise JobPostingError(
        "A página não tem dados estruturados de vaga reconhecíveis; leia a vaga pelo navegador.")


# --- Acesso ------------------------------------------------------------------------------------

def site_key(host: str) -> str:
    """Subdomínios do mesmo site contam juntos no intervalo (br.linkedin.com = www.linkedin.com)."""
    host = host.lower()
    for site in ("linkedin.com", "gupy.io", "indeed.com", "glassdoor.com"):
        if host == site or host.endswith("." + site) or f".{site}." in host:
            return site
    return host


def min_interval(host: str) -> float:
    """Segundos entre requisições ao mesmo site: VAGAS_SITE_MIN_SECONDS (3); LinkedIn mais espaçado
    (VAGAS_LINKEDIN_JOBS_MIN_SECONDS, 20), porque ele limita leituras seguidas (429)."""
    if site_key(host) == "linkedin.com":
        return float(os.environ.get("VAGAS_LINKEDIN_JOBS_MIN_SECONDS") or 20)
    return float(os.environ.get("VAGAS_SITE_MIN_SECONDS") or 3)


def http_fetch(url: str) -> tuple[int, str]:
    """GET com User-Agent honesto e intervalo mínimo por site (min_interval)."""
    host = urlsplit(url).netloc.lower()
    key = site_key(host)
    wait = min_interval(host) - (time.monotonic() - _last_request.get(key, -1e9))
    if wait > 0:
        time.sleep(wait)
    _last_request[key] = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise JobPostingError(f"Não foi possível acessar {url}: {exc.reason}.") from exc


def read_job_posting(url: str, fetcher: Fetcher = http_fetch) -> dict[str, Any]:
    url = url.strip()
    linkedin = _source(url) == "linkedin"
    canonical = canonical_url(url) or url
    if linkedin and "/jobs/view/" in canonical:
        url = "https://www.linkedin.com/jobs/view/" + canonical.rsplit("/", 1)[1] + "/"
    status, page = fetcher(url)
    host = urlsplit(url).netloc
    if linkedin and status in (429, 999):
        raise JobPostingError("O LinkedIn limitou as leituras automáticas por enquanto; espere alguns minutos "
                              "ou leia a vaga pelo navegador.")
    if linkedin and ("authwall" in page or re.search(r"<title>[^<]*(Sign Up|Sign In|Entrar|Cadastre-se)[^<]*"
                                                     r"\| LinkedIn", page)):
        raise JobPostingError("O LinkedIn pediu login para mostrar a vaga; leia a vaga pelo navegador.")
    if status in (401, 403, 429) or _BLOCKED.search(page[:5000]):
        raise JobPostingError(
            f"O site {host} bloqueou a leitura automática (proteção anti-robô); leia a vaga pelo navegador.")
    if status != 200:
        raise JobPostingError(f"O site {host} respondeu {status} para {url}.")
    return extract_job(url, page)
