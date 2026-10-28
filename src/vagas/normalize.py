"""Normalização de empresa e URL usada na deduplicação."""

import base64
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_COMPANY_SUFFIXES = {"ltda", "sa", "inc", "llc", "ltd", "me", "eireli"}


def normalize_text(text: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados ("  Pythón  Remoto" -> "python remoto")."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(ascii_text.lower().split())


def normalize_company(name: str) -> str:
    """Minúsculas, sem acentos e pontuação, sem sufixo societário no fim ("Itaú Unibanco S.A." -> "itau unibanco")."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    tokens = re.findall(r"[a-z0-9&]+", ascii_name)
    if tokens[-2:] == ["s", "a"]:  # "S.A." e "S/A" viram "sa"
        tokens[-2:] = ["sa"]
    while len(tokens) > 1:
        if tokens[-1] in _COMPANY_SUFFIXES:
            del tokens[-1]
        else:
            break
    return " ".join(tokens)


_TRACKING_PARAMS = {"trk", "refid", "trackingid"}


def canonical_url(url: str | None) -> str | None:
    """Forma comparável da URL de uma vaga.

    LinkedIn, Gupy, Indeed e Glassdoor são reduzidos ao identificador da vaga, para que links de
    busca, coleções, slugs, subdomínios de país e parâmetros de origem caiam na mesma forma. Outros
    sites: https, host minúsculo sem "www.", sem fragmento, sem barra final e sem parâmetros de
    rastreamento (utm_*, trk, refId, trackingId).
    """
    if url is None or not url.strip():
        return None
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    params = parse_qsl(parts.query, keep_blank_values=True)
    platform = _platform_url(host, path, {key.lower(): value for key, value in params})
    if platform is not None:
        return platform
    query = sorted(
        (key, value) for key, value in params
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    )
    return urlunsplit(("https", host, path, urlencode(query), ""))


def _gupy_short_link_id(path: str) -> str | None:
    """Links /job/<base64 de {"jobId": N, ...}> do portal da Gupy."""
    match = re.fullmatch(r"/job/([A-Za-z0-9+/=_-]+)", path)
    if not match:
        return None
    token = match.group(1)
    try:
        data = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except (ValueError, TypeError):
        return None
    job_id = data.get("jobId") if isinstance(data, dict) else None
    return str(job_id) if job_id else None


def _platform_url(host: str, path: str, query: dict[str, str]) -> str | None:
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        match = re.search(r"/jobs/view/(?:[^/]*-)?(\d+)$", path)
        job = match.group(1) if match else query.get("currentjobid", "")
        return f"https://linkedin.com/jobs/view/{job}" if job.isdigit() else None
    if host.endswith(".gupy.io"):
        match = re.fullmatch(r"/jobs/(\d+)", path)
        if match:
            return f"https://{host}/jobs/{match.group(1)}"
        job_id = _gupy_short_link_id(path)
        return f"https://{host}/jobs/{job_id}" if job_id else None
    if host == "indeed.com" or host.endswith(".indeed.com"):
        job = query.get("jk") or query.get("vjk")
        return f"https://indeed.com/viewjob?jk={job}" if job else None
    if re.fullmatch(r"(?:[\w-]+\.)?glassdoor\.[a-z.]+", host):
        job = query.get("jl") or query.get("joblistingid")
        return f"https://glassdoor.com/job-listing?jl={job}" if job else None
    return None
