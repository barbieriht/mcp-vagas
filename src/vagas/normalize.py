"""Normalização de empresa e URL usada na deduplicação."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_company(name: str) -> str:
    return " ".join(name.lower().split())


def canonical_url(url: str | None) -> str | None:
    """Forma comparável da URL: https, host minúsculo, sem fragmento nem parâmetros utm_*."""
    if url is None or not url.strip():
        return None
    parts = urlsplit(url.strip())
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    )
    path = parts.path.rstrip("/")
    return urlunsplit(("https", parts.netloc.lower(), path, urlencode(query), ""))
