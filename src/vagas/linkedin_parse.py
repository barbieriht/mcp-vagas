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


# --- Experience, Education, Volunteering ------------------------------------------------------

_PERIOD = re.compile(r"^(?P<start>[A-Z][a-z]{2} \d{4}|\d{4})\s*[-–]\s*(?P<end>[A-Z][a-z]{2} \d{4}|\d{4}|Present)\b")
_EMPLOYMENT = {"Full-time", "Part-time", "Self-employed", "Freelance", "Contract", "Internship", "Apprenticeship",
               "Seasonal", "Temporary", "Trainee"}
_MODES = {"Remote": "remote", "Hybrid": "hybrid", "On-site": "onsite"}
_SKILLS = re.compile(r"^Skills:|\+\d+ skills?$")
_ATTACHMENT = re.compile(r"\.(pdf|docx?|pptx?|xlsx?|png|jpe?g)$", re.IGNORECASE)
_TRUNCATED = re.compile(r"\s*(…|\.\.\.)\s*(see )?more$")
_QUALIFIER = re.compile(r"^(?P<title>.+?)\s*\((?P<context>[^()]+)\)$")


def _period(line: str) -> tuple[str, str] | None:
    match = _PERIOD.match(line)
    return (match.group("start"), match.group("end")) if match else None


def _place(line: str) -> dict[str, str] | None:
    """"São Paulo, Brazil · Hybrid" -> location e work_mode; "Remote" -> work_mode; outra coisa -> None."""
    location, _, mode = line.rpartition(" · ")
    if mode in _MODES:
        return {"location": location, "work_mode": _MODES[mode]} if location else {"work_mode": _MODES[mode]}
    if line in _MODES:
        return {"work_mode": _MODES[line]}
    if "," in line and len(line) < 80 and not line.endswith("."):
        return {"location": line}
    return None


def _paragraphs(item_id: str, lines: list[str], warnings: list[str], where: str) -> tuple[list[dict], list[str]]:
    paragraphs, attachments = [], []
    for line in lines:
        if _SKILLS.search(line):
            continue
        if _ATTACHMENT.search(line):
            attachments.append(line)
            continue
        if _TRUNCATED.search(line):
            line = _TRUNCATED.sub("", line).strip()
            warnings.append(f"{where}: descrição cortada (\"… more\"); confira o texto completo no LinkedIn.")
        if not line:
            continue
        paragraphs.append({"id": f"{item_id}-p{len(paragraphs) + 1}", "text": line})
    return paragraphs, attachments


def parse_experience(blocks: list[dict[str, Any]]) -> tuple[list[dict], dict[str, dict], list[str]]:
    """Blocos de /details/experience/ -> itens de experience, extras (anexos por item) e avisos.
    Uma empresa com vários cargos vem como cabeçalho + "roles"; cada cargo vira um item."""
    items, extras, warnings, used = [], {}, [], set()

    def role(lines: list[str], company: str | None, default_place: dict[str, str]) -> None:
        if not lines:
            return
        title, rest = lines[0], lines[1:]
        if company is None and rest:
            company, _, _ = rest.pop(0).partition(" · ")
        if rest and rest[0] in _EMPLOYMENT:
            rest.pop(0)
        if not rest or not (period := _period(rest[0])):
            warnings.append(f"Experiência \"{title}\" sem período reconhecível; não importada.")
            return
        rest.pop(0)
        place = dict(default_place)
        if rest and (found := _place(rest[0])):
            place.update(found)
            rest.pop(0)
        item: dict[str, Any] = {"company": company or "Unknown"}
        if qualified := _QUALIFIER.match(title):
            title, item["context"] = qualified.group("title"), qualified.group("context")
        item_id = _unique(f"exp-{slug(item['company'], 24)}-{slug(title, 32)}", used)
        item = {"id": item_id, **item, "title": title, **place, "start": period[0], "end": period[1]}
        item["paragraphs"], attachments = _paragraphs(item_id, rest, warnings, f"Experiência \"{title}\"")
        if not item["paragraphs"]:
            warnings.append(f"Experiência \"{title}\" sem descrição no LinkedIn.")
        if attachments:
            extras[item_id] = {"attachments": attachments}
        items.append(item)

    for block in blocks:
        if block.get("roles"):
            header = block.get("lines", [])
            company = header[0] if header else None
            default_place = next((p for line in header[1:] if (p := _place(line))), {})
            for sub in block["roles"]:
                role(list(sub.get("lines", [])), company, default_place)
        else:
            role(list(block.get("lines", [])), None, {})
    return items, extras, warnings


def parse_education(blocks: list[dict[str, Any]], today: str) -> tuple[list[dict], list[str]]:
    """Blocos de /details/education/ -> itens de education; término no futuro vira "Present" + previsão."""
    items, warnings, used = [], [], set()
    for block in blocks:
        lines = list(block.get("lines", []))
        if not lines:
            continue
        item: dict[str, Any] = {"institution": lines.pop(0)}
        if lines and not _period(lines[0]):
            degree, _, field = lines.pop(0).partition(", ")
            item["degree"] = degree
            if field:
                item["field"] = field
        else:
            item["degree"] = "Unknown"
            warnings.append(f"Formação em {item['institution']} sem grau no LinkedIn.")
        notes = []
        if lines and (period := _period(lines[0])):
            lines.pop(0)
            item["start"], item["end"] = period
            end = month_year(period[1])
            if end and end > today[:len(end)]:
                item["end"] = "Present"
                notes.append(f"Expected {period[1]}")
        notes += [line for line in lines if not _SKILLS.search(line)]
        if notes:
            item["notes"] = "; ".join(notes)
        item = {"id": _unique(f"edu-{slug(item['institution'], 24)}-{slug(item['degree'], 24)}", used), **item}
        items.append(item)
    return items, warnings


def parse_volunteering(blocks: list[dict[str, Any]]) -> tuple[list[dict], list[str]]:
    """Blocos de /details/volunteering-experiences/ -> itens de volunteering."""
    items, warnings, used = [], [], set()
    for block in blocks:
        lines = list(block.get("lines", []))
        if len(lines) < 2:
            continue
        role, organization, rest = lines[0], lines[1], lines[2:]
        item_id = _unique(f"vol-{slug(organization, 24)}-{slug(role, 32)}", used)
        item: dict[str, Any] = {"id": item_id, "organization": organization, "role": role}
        if rest and (period := _period(rest[0])):
            rest.pop(0)
            item["start"], item["end"] = period
        if rest and len(rest[0]) < 60 and not rest[0].endswith("."):
            rest.pop(0)  # causa ("Education", "Civil Rights and Social Action")
        item["paragraphs"], _ = _paragraphs(item_id, rest, warnings, f"Voluntariado \"{role}\"")
        items.append(item)
    return items, warnings


def section_text(items: list[dict[str, Any]], extras: dict[str, dict] | None = None) -> str:
    """Texto de uma seção para registro como fonte (todos os valores dos itens, anexos incluídos)."""
    def values(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                if key != "id":
                    yield from values(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from values(inner)
        elif value is not None:
            yield str(value)

    blocks = []
    for item in items:
        lines = list(values(item)) + list(values((extras or {}).get(item.get("id"), {})))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
