"""Normalização de empresa e URL usada na deduplicação."""

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_COMPANY_SUFFIXES = {"ltda", "sa", "inc", "llc", "ltd", "me", "eireli"}


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
