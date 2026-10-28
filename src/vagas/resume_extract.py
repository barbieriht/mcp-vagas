"""Extração de texto do PDF do currículo e relatório de revisão do rascunho contra esse texto.

O relatório é um aviso para o usuário conferir, não um bloqueio: a extração de texto de PDF é
imperfeita. A comparação "espreme" os dois lados (minúsculas, sem espaços, ligaduras desfeitas,
traços unificados) e aceita a hifenização de fim de linha com e sem o hífen, o que tolera palavras
coladas ("EnglishUpper-intermediate") e quebras de linha no meio de nomes.
"""

import re
import unicodedata
from pathlib import Path
from typing import Any

import pypdf
from pypdf.errors import PdfReadError

from vagas.repo import VagasError
from vagas.resume_validate import numbers, term_candidates

_DASHES = str.maketrans({"–": "-", "—": "-", "‐": "-", "‑": "-", "’": "'", "‘": "'", "“": '"', "”": '"'})

# Campos curtos conferidos por inteiro; textos longos são conferidos por número e termo.
_WHOLE_FIELDS = {
    "basics": ("name", "headline", "email", "phone", "location"),
    "education": ("institution", "degree", "field", "start", "end"),
    "experience": ("company", "context", "title", "location", "start", "end"),
    "volunteering": ("organization", "role", "location", "start", "end"),
    "projects": ("name", "link", "start", "end"),
    "publications": ("title", "venue", "authors", "link", "year"),
}
_LONG_FIELDS = {"education": "notes"}


def wsl_path(path: str | Path) -> Path:
    """Aceita caminhos do Windows (C:\\Users\\...) e devolve o equivalente no WSL (/mnt/c/Users/...)."""
    text = str(path)
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if match:
        return Path("/mnt", match.group(1).lower(), *re.split(r"[\\/]+", match.group(2)))
    return Path(text)


def extract_pages(path: Path) -> list[str]:
    if not path.exists():
        raise VagasError(f"O arquivo {path} não existe.")
    try:
        reader = pypdf.PdfReader(path)
        pages = [unicodedata.normalize("NFKC", page.extract_text() or "") for page in reader.pages]
    except (PdfReadError, ValueError) as exc:
        raise VagasError(f"{path} não é um PDF válido: {exc}") from exc
    if not any(page.strip() for page in pages):
        raise VagasError(f"{path} é um PDF sem texto (provavelmente escaneado); OCR não é suportado.")
    return pages


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).translate(_DASHES).lower())


def review_draft(draft: dict[str, Any], reference: str) -> list[dict[str, str]]:
    """Itens do rascunho que não foram encontrados no texto de referência, com o local (ID)."""
    variants = (_squash(reference), _squash(re.sub(r"-[ \t]*\n\s*", "", reference)))
    review: list[dict[str, str]] = []

    def found(value: Any) -> bool:
        squashed = _squash(str(value))
        return not squashed or any(squashed in v for v in variants)

    def check(where: str, value: Any, reason: str) -> None:
        if value is None:
            return
        if not found(value):
            item = {"where": where, "value": str(value), "reason": reason}
            if item not in review:
                review.append(item)

    def check_whole(where: str, value: Any) -> None:
        check(where, value, "não encontrado nas fontes")

    def check_long(where: str, text: str | None) -> None:
        if text is None:
            return
        for number in numbers(text):
            check(where, number, "número não encontrado nas fontes")
        for term in term_candidates(text):
            check(where, term, "termo não encontrado nas fontes")

    basics = draft.get("basics", {})
    for field in _WHOLE_FIELDS["basics"]:
        check_whole(f"basics.{field}", basics.get(field))
    for link in basics.get("links", []):
        check_whole("basics.links", link)
    for variant in basics.get("headline_variants", []):
        check_whole("basics.headline_variants", variant)
    check_long("summary", draft.get("summary"))

    for section in ("education", "experience", "volunteering", "projects", "publications"):
        for item in draft.get(section, []):
            item_id = item.get("id", section)
            for field in _WHOLE_FIELDS[section]:
                check_whole(f"{item_id}.{field}", item.get(field))
            for alias in item.get("title_aliases", []):
                check_whole(f"{item_id}.title_aliases", alias)
            if section in _LONG_FIELDS:
                check_long(item_id, item.get(_LONG_FIELDS[section]))
            for paragraph in item.get("paragraphs", []):
                check_long(paragraph.get("id", item_id), paragraph.get("text"))

    for group in draft.get("skills", []):
        check_whole(f"{group['id']}.label", group.get("label"))
        for term in group.get("terms", []):
            check_whole(f"{group['id']}.terms", term)
    for group in draft.get("certifications", []):
        check_whole(f"{group['id']}.label", group.get("label"))
        for cert in group.get("items", []):
            names = [cert.get("name"), cert.get("name_original")]
            if not any(found(name) for name in names if name):
                check_whole(f"{cert['id']}.name", cert.get("name"))
            for field in ("provider", "year", "credential_id", "link"):
                check_whole(f"{cert['id']}.{field}", cert.get(field))
            if cert.get("issued"):
                check_whole(f"{cert['id']}.issued", cert["issued"][:4])
            check_long(f"{cert['id']}.description", cert.get("description"))
    for i, language in enumerate(draft.get("languages", [])):
        for field in ("name", "level", "note"):
            check_whole(f"languages.{i}.{field}", language.get(field))
    return review
