"""Currículo personalizado: seleção sobre o currículo geral e resolução com verificação anti-invenção."""

import copy
from typing import Any, Literal

from pydantic import Field

from vagas.repo import VagasError
from vagas.resume_model import Id, Text, _Model
from vagas.resume_validate import number_set, strings, term_set, unknown_numbers, unknown_terms

Section = Literal[
    "education", "experience", "volunteering", "projects", "publications", "skills", "certifications", "languages",
]
DEFAULT_ORDER: tuple[str, ...] = (
    "education", "experience", "volunteering", "projects", "publications", "skills", "certifications", "languages",
)
_WITH_PARAGRAPHS = {"experience", "volunteering", "projects"}


class ParagraphPick(_Model):
    id: Id
    bullets: list[Text] | None = Field(
        None, min_length=1,
        description="Reescrita do parágrafo como bullets. Sem isto, o parágrafo entra como está.",
    )


class ItemPick(_Model):
    id: Id
    paragraphs: list[ParagraphPick] | None = Field(
        None, description="Só experience/volunteering/projects. Parágrafos e ordem; ausente = todos, como estão.",
    )
    terms: list[Text] | None = Field(None, description="Só skills. Subconjunto e ordem dos termos do grupo.")
    items: list[Id] | None = Field(None, description="Só certifications. IDs das certificações do grupo.")
    title: Text | None = Field(
        None, description="Só experience. O título ou um dos title_aliases do currículo geral; ausente = o título.")


class SectionPick(_Model):
    section: Section
    items: list[ItemPick] | None = Field(
        None, description="Itens e ordem; ausente = todos os itens da seção. languages não aceita items.",
    )


class TailoredSelection(_Model):
    """Seleção sobre o currículo geral. Campos factuais (empresa, organização, cargo, papel, datas,
    local, instituição, grau, certificação, idioma) não são aceitos: vêm sempre do currículo geral."""

    label: Text | None = Field(None, description="Empresa ou rótulo usado no nome do arquivo")
    headline: Text | None = Field(None, description="Headline reescrita; ausente = a do currículo geral")
    summary: Text | None = Field(None, description="Resumo; ausente = o do currículo geral, se houver")
    sections: list[SectionPick] = Field(min_length=1, description="Seções na ordem em que devem aparecer")


def resolve(master: dict[str, Any], selection: TailoredSelection) -> dict[str, Any]:
    """Monta o conteúdo final; levanta VagasError listando todos os problemas encontrados."""
    evidence = _without_course_descriptions(master)
    corpus_terms = term_set(strings(evidence))
    corpus_numbers = number_set(strings(evidence))
    errors: list[str] = []

    basics = copy.deepcopy(master["basics"])
    resolved: dict[str, Any] = {"basics": basics, "order": []}
    for field in ("headline", "summary"):
        text = getattr(selection, field)
        if text is not None:
            errors += _check(field, text, corpus_numbers, corpus_terms, "no currículo geral")
    if selection.headline is not None:
        basics["headline"] = selection.headline
    summary = selection.summary if selection.summary is not None else master.get("summary")
    if summary is not None:
        resolved["summary"] = summary

    for pick in selection.sections:
        if pick.section in resolved["order"]:
            errors.append(f"seção {pick.section!r} repetida")
            continue
        resolved["order"].append(pick.section)
        resolved[pick.section] = _resolve_section(master, pick, corpus_numbers, corpus_terms, errors)

    if errors:
        raise VagasError(
            "Seleção rejeitada; corrija a seleção ou o texto (nunca contorne):\n"
            + "\n".join(f"- {e}" for e in errors)
        )
    return resolved


def _without_course_descriptions(master: dict[str, Any]) -> dict[str, Any]:
    """Currículo sem as descrições de certificação: conteúdo de curso não comprova experiência."""
    evidence = copy.deepcopy(master)
    for group in evidence.get("certifications", []):
        for cert in group.get("items", []):
            cert.pop("description", None)
    return evidence


def _resolve_section(master, pick: SectionPick, corpus_numbers, corpus_terms, errors) -> list[dict[str, Any]]:
    available = master.get(pick.section, [])
    if pick.items is None:
        return copy.deepcopy(available)
    if pick.section == "languages":
        errors.append("a seção 'languages' não aceita items: ela entra completa")
        return []

    by_id = {item["id"]: item for item in available}
    chosen, seen = [], set()
    for item_pick in pick.items:
        where = item_pick.id
        if item_pick.id in seen:
            errors.append(f"{where}: item repetido")
            continue
        seen.add(item_pick.id)
        item = by_id.get(item_pick.id)
        if item is None:
            errors.append(f"{where}: não existe na seção {pick.section!r} do currículo geral")
            continue
        for field, allowed in (("paragraphs", _WITH_PARAGRAPHS), ("terms", {"skills"}), ("items", {"certifications"}),
                               ("title", {"experience"})):
            if getattr(item_pick, field) is not None and pick.section not in allowed:
                errors.append(f"{where}: {field!r} não se aplica à seção {pick.section!r}")
        item = copy.deepcopy(item)
        if pick.section == "experience" and item_pick.title is not None:
            options = {t.casefold(): t for t in [item["title"], *item.get("title_aliases", [])]}
            if item_pick.title.casefold() in options:
                item["title"] = options[item_pick.title.casefold()]
            else:
                errors.append(f"{where}: título {item_pick.title!r} não é o título nem um dos title_aliases registrados")
        if pick.section in _WITH_PARAGRAPHS and item_pick.paragraphs is not None:
            item["paragraphs"] = _resolve_paragraphs(item, item_pick, corpus_terms, errors)
        if pick.section == "skills" and item_pick.terms is not None:
            item["terms"] = _subset(where, "termo", item["terms"], item_pick.terms, str.lower, errors)
        if pick.section == "certifications" and item_pick.items is not None:
            certs = {c["id"]: c for c in item["items"]}
            item["items"] = [certs[i] for i in _subset(where, "certificação", list(certs), item_pick.items, str, errors)]
        chosen.append(item)
    return chosen


def _resolve_paragraphs(item, item_pick: ItemPick, corpus_terms, errors) -> list[dict[str, Any]]:
    by_id = {p["id"]: p for p in item["paragraphs"]}
    resolved = []
    for paragraph_pick in item_pick.paragraphs:
        source = by_id.get(paragraph_pick.id)
        if source is None:
            errors.append(f"{paragraph_pick.id}: não é parágrafo de {item['id']}")
            continue
        if paragraph_pick.bullets is None:
            resolved.append(source)
            continue
        allowed_numbers = number_set([source["text"]])
        for n, bullet in enumerate(paragraph_pick.bullets, start=1):
            errors += _check(f"{source['id']} (bullet {n})", bullet, allowed_numbers, corpus_terms,
                             "no parágrafo de origem")
        resolved.append({"id": source["id"], "bullets": paragraph_pick.bullets})
    return resolved


def _subset(where, kind, available, requested, key, errors) -> list[str]:
    index = {key(value): value for value in available}
    result = []
    for value in requested:
        match = index.get(key(value))
        if match is None:
            errors.append(f"{where}: {kind} {value!r} não está no grupo do currículo geral")
        else:
            result.append(match)
    return result


def _check(where, text, allowed_numbers, corpus_terms, number_scope) -> list[str]:
    problems = [f"{where}: número {n!r} não aparece {number_scope}" for n in unknown_numbers(text, allowed_numbers)]
    problems += [f"{where}: termo {t!r} não aparece no currículo geral" for t in unknown_terms(text, corpus_terms)]
    return problems
