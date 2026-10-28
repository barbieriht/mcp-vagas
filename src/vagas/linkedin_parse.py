"""Interpretação dos blocos lidos das páginas de detalhes do LinkedIn. Funções puras, sem navegador.

Um bloco é um item da lista da página: {"lines": [texto visível, linha a linha], "links": [{text, href}]}.
O navegador só separa os blocos; tudo o que é regra (datas, campos, links, duplicatas) fica aqui.
"""

import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlsplit

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_YEAR = re.compile(r"\b([A-Z][a-z]{2})[a-z]*\.? (\d{4})\b")
_YEAR = re.compile(r"^\s*(\d{4})\s*$")
_HEADINGS = {"Licenses & certifications", "Licenças e certificados"}


def month_year(text: str) -> str | None:
    """"Issued Oct 2026" -> "2026-10"; "2019" -> "2019"; sem data reconhecível -> None."""
    match = _MONTH_YEAR.search(text)
    if match and match.group(1).lower() in _MONTHS:
        return f"{match.group(2)}-{_MONTHS[match.group(1).lower()]:02d}"
    match = _YEAR.match(text)
    return match.group(1) if match else None


def unwrap_link(href: str) -> str:
    """Links externos vêm embrulhados em linkedin.com/safety/go/?url=<endereço>."""
    parts = urlsplit(href)
    if parts.netloc.endswith("linkedin.com") and parts.path.startswith("/safety/go"):
        target = parse_qs(parts.query).get("url")
        if target:
            return target[0]
    return href


def slug(text: str, limit: int = 48) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return "-".join(re.findall(r"[a-z0-9]+", ascii_text))[:limit].strip("-") or "item"


def _unique(base: str, used: set[str]) -> str:
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    used.add(candidate)
    return candidate


def parse_certifications(blocks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Blocos de /details/certifications/ -> grupos (por emissor) no formato do currículo geral e avisos."""
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    by_credential: dict[str, dict[str, Any]] = {}
    used_ids: set[str] = set()
    for number, block in enumerate(blocks, start=1):
        lines = block.get("lines", [])
        if lines and lines[0] in _HEADINGS and len(lines) == 1:
            continue
        if not lines:
            warnings.append(f"Bloco {number} de certificações não reconhecido (sem texto).")
            continue
        item: dict[str, Any] = {"name": lines[0]}
        rest = lines[1:]
        if rest and not rest[0].startswith(("Issued", "Credential ID", "Show credential", "Skills:")):
            item["provider"] = rest.pop(0)
        trailing: list[str] = []
        for line in rest:
            if line.startswith("Issued"):
                if issued := month_year(line):
                    item["issued"] = issued
            elif line.startswith("Credential ID"):
                item["credential_id"] = line.removeprefix("Credential ID").strip()
            elif line == "Show credential" or line.startswith("Skills:"):
                continue
            else:
                trailing.append(line)
        # Depois dos campos vem o cartão de mídia: título repetido, descrição e/ou nomes de arquivo anexos.
        description = [t for t in trailing if t != item["name"] and not re.search(r"\.\w{2,4}$", t)]
        if len(description) > 1 and len(description[0]) < 80 and not description[0].endswith("."):
            description = description[1:]  # título do cartão de mídia antes da descrição
        if description:
            item["description"] = " ".join(description)
        link = next((l["href"] for l in block.get("links", []) if l.get("text") == "Show credential"), None)
        if link:
            item["link"] = unwrap_link(link)

        credential = item.get("credential_id")
        if credential and credential in by_credential:
            kept = by_credential[credential]
            warnings.append(
                f"Credencial {credential} aparece duas vezes no LinkedIn ({kept['name']}); mantida a emissão mais "
                "antiga. Vale corrigir a duplicata no LinkedIn."
            )
            if item.get("issued") and (not kept.get("issued") or item["issued"] < kept["issued"]):
                kept["issued"] = item["issued"]
            continue
        item = {"id": _unique(f"cert-{slug(item['name'])}", used_ids), **item}
        if credential:
            by_credential[credential] = item
        items.append(item)

    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        label = item.get("provider", "Other")
        group = groups.setdefault(label, {"id": f"certs-{slug(label)}", "label": label, "items": []})
        group["items"].append(item)
    return list(groups.values()), warnings


def certifications_text(groups: list[dict[str, Any]]) -> str:
    """Texto da seção para registro como fonte do currículo (links incluídos)."""
    lines = []
    for group in groups:
        for item in group["items"]:
            fields = [item["name"], item.get("provider"), item.get("issued"),
                      item.get("credential_id") and f"Credential ID {item['credential_id']}", item.get("link"),
                      item.get("description")]
            lines.append("\n".join(f for f in fields if f))
    return "\n\n".join(lines)
