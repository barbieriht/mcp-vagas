"""Diferenças entre itens vindos das fontes (ex.: import_linkedin_profile) e o currículo geral aprovado.

Não depende de MCP nem do banco: recebe o currículo aprovado e os itens, e devolve o que é novo, o que
mudou (com os campos) e o que não veio nas fontes, mais o rascunho com os novos acrescentados. Itens
existentes mantêm o ID (currículos personalizados apontam para eles); nada é removido e as alterações
não são aplicadas sozinhas: a LLM revisa, decide e salva com save_master_draft.

Chaves naturais, comparadas sem maiúsculas, acentos e pontuação (com tolerância a pequenas grafias):
experience = empresa + cargo (ou alias) + início; certifications = credential_id, senão nome + emissor;
education = instituição + grau; volunteering = organização + papel; languages = nome; skills = termo.
"""

import copy
import re
from difflib import SequenceMatcher
from typing import Any

from vagas.linkedin_parse import month_year, slug
from vagas.normalize import normalize_company, normalize_text

SIMILARITY = 0.9
_LIST_SECTIONS = ("experience", "education", "volunteering")
_FIELDS = {
    "experience": ("company", "context", "title", "location", "work_mode", "start", "end"),
    "education": ("institution", "degree", "field", "notes", "start", "end"),
    "volunteering": ("organization", "role", "location", "work_mode", "start", "end"),
    "certifications": ("name", "name_original", "provider", "year", "issued", "credential_id", "link",
                       "description"),
}
_DATES = {"start", "end"}


def _norm(text: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", normalize_text(str(text)))) if text is not None else ""


def _similar(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or SequenceMatcher(None, a, b).ratio() >= SIMILARITY)


def _date(text: Any) -> str:
    if text is None or _norm(text) in ("", "present", "atual", "presente", "current"):
        return "present"
    text = str(text)
    numeric = re.fullmatch(r"\s*(\d{1,2})/(\d{4})\s*", text)
    if numeric:
        return f"{numeric.group(2)}-{int(numeric.group(1)):02d}"
    return month_year(text) or _norm(text)


def _same_value(field: str, old: Any, new: Any) -> bool:
    if field in _DATES:
        return _date(old) == _date(new)
    if field in ("company", "organization", "institution"):
        return normalize_company(str(old or "")) == normalize_company(str(new or ""))
    return _norm(old) == _norm(new)


def _texts(paragraphs: list[dict[str, Any]] | None) -> list[str]:
    return [p["text"] for p in paragraphs or []]


def _titles(item: dict[str, Any]) -> set[str]:
    return {_norm(t) for t in [item.get("title"), *item.get("title_aliases", [])] if t}


def _matches(section: str, old: dict[str, Any], new: dict[str, Any]) -> bool:
    if section == "experience":
        return (_similar(normalize_company(old["company"]), normalize_company(new["company"]))
                and any(_similar(a, b) for a in _titles(old) for b in _titles(new))
                and _date(old.get("start")) == _date(new.get("start")))
    if section == "education":
        return (_similar(normalize_company(old["institution"]), normalize_company(new["institution"]))
                and _similar(_norm(old["degree"]), _norm(new["degree"])))
    if section == "volunteering":
        return (_similar(normalize_company(old["organization"]), normalize_company(new["organization"]))
                and _similar(_norm(old["role"]), _norm(new["role"])))
    if section == "certifications":
        if old.get("credential_id") and new.get("credential_id"):
            return _norm(old["credential_id"]) == _norm(new["credential_id"])
        names_old = {_norm(old.get("name")), _norm(old.get("name_original"))} - {""}
        names_new = {_norm(new.get("name")), _norm(new.get("name_original"))} - {""}
        return (any(_similar(a, b) for a in names_old for b in names_new)
                and _norm(old.get("provider")) == _norm(new.get("provider")))
    raise ValueError(section)


def _changes(section: str, old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for field in _FIELDS[section]:
        if new.get(field) is None or _same_value(field, old.get(field), new[field]):
            continue
        if field == "title" and _norm(new["title"]) in _titles(old):
            continue  # forma alternativa já registrada em title_aliases
        fields[field] = {"old": old.get(field), "new": new[field]}
    if "paragraphs" in new and [_norm(t) for t in _texts(old.get("paragraphs"))] != [
            _norm(t) for t in _texts(new.get("paragraphs"))]:
        fields["paragraphs"] = {"old": _texts(old.get("paragraphs")), "new": _texts(new.get("paragraphs"))}
    return fields


class _Ids:
    def __init__(self, resume: dict[str, Any]):
        self.used: set[str] = set()
        for section in ("education", "experience", "volunteering", "projects", "publications", "skills",
                        "certifications"):
            for item in resume.get(section, []):
                self.used.add(item["id"])
                self.used.update(p["id"] for p in item.get("paragraphs", []))
                self.used.update(c["id"] for c in item.get("items", []))

    def new(self, base: str) -> str:
        candidate, n = base, 2
        while candidate in self.used:
            candidate, n = f"{base}-{n}", n + 1
        self.used.add(candidate)
        return candidate

    def item(self, item: dict[str, Any], fallback: str) -> dict[str, Any]:
        item = copy.deepcopy(item)
        item["id"] = self.new(item.get("id") or slug(fallback))
        if "paragraphs" in item:
            item["paragraphs"] = [{**p, "id": self.new(f"{item['id']}-p{n}")}
                                  for n, p in enumerate(item["paragraphs"], start=1)]
        return item


def diff_master(master: dict[str, Any], items: dict[str, Any]) -> dict[str, Any]:
    draft = copy.deepcopy(master)
    ids = _Ids(master)
    new: dict[str, Any] = {}
    changed: list[dict[str, Any]] = []
    missing: dict[str, list[str]] = {}

    def change(section: str, item_id: str, fields: dict[str, Any]) -> None:
        if fields:
            changed.append({"section": section, "id": item_id, "fields": fields})

    basics = master.get("basics", {})
    if items.get("headline") and not _same_value("headline", basics.get("headline"), items["headline"]):
        change("basics", "headline", {"headline": {"old": basics.get("headline"), "new": items["headline"]}})
    if items.get("summary") and not _same_value("summary", master.get("summary"), items["summary"]):
        change("summary", "summary", {"summary": {"old": master.get("summary"), "new": items["summary"]}})

    for section in _LIST_SECTIONS:
        if section not in items:
            continue
        existing = master.get(section, [])
        seen: set[str] = set()
        for incoming in items[section] or []:
            match = next((old for old in existing if old["id"] not in seen and _matches(section, old, incoming)), None)
            if match is None:
                label = " ".join(str(incoming.get(k, "")) for k in _FIELDS[section][:2])
                added = ids.item(incoming, f"{section[:3]}-{label}")
                new.setdefault(section, []).append(added)
                draft.setdefault(section, []).append(added)
                continue
            seen.add(match["id"])
            change(section, match["id"], _changes(section, match, incoming))
        absent = [old["id"] for old in existing if old["id"] not in seen]
        if absent:
            missing[section] = absent

    if "certifications" in items:
        _certifications(master, draft, items["certifications"] or [], ids, new, change, missing)
    if "languages" in items:
        _languages(master, draft, items["languages"] or [], new, change, missing)
    if items.get("skills"):
        _skills(master, draft, items["skills"], ids, new)

    return {"new": new, "changed": changed, "missing": missing, "draft": draft}


def _certifications(master, draft, groups, ids, new, change, missing) -> None:
    existing = [(g, c) for g in master.get("certifications", []) for c in g["items"]]
    seen: set[str] = set()
    for group in groups:
        for incoming in group.get("items", []):
            match = next((c for _, c in existing if c["id"] not in seen
                          and _matches("certifications", c, incoming)), None)
            if match:
                seen.add(match["id"])
                change("certifications", match["id"], _changes("certifications", match, incoming))
                continue
            added = ids.item(incoming, f"cert-{incoming.get('name', '')}")
            new.setdefault("certifications", []).append(added)
            target = next((g for g in draft.setdefault("certifications", [])
                           if _norm(g["label"]) == _norm(group.get("label"))), None)
            if target is None:
                target = {"id": ids.new(group.get("id") or slug(f"cert-{group.get('label', '')}")),
                          "label": group.get("label") or "Certifications", "items": []}
                draft["certifications"].append(target)
            target["items"].append(added)
    absent = [c["id"] for _, c in existing if c["id"] not in seen]
    if absent:
        missing["certifications"] = absent


def _languages(master, draft, languages, new, change, missing) -> None:
    existing = master.get("languages", [])
    seen: set[str] = set()
    for incoming in languages:
        match = next((l for l in existing if _norm(l["name"]) == _norm(incoming.get("name"))), None)
        if match is None:
            new.setdefault("languages", []).append(copy.deepcopy(incoming))
            draft.setdefault("languages", []).append(copy.deepcopy(incoming))
            continue
        seen.add(match["name"])
        fields = {f: {"old": match.get(f), "new": incoming[f]} for f in ("level", "note")
                  if incoming.get(f) is not None and not _same_value(f, match.get(f), incoming[f])}
        change("languages", match["name"], fields)
    absent = [l["name"] for l in existing if l["name"] not in seen]
    if absent:
        missing["languages"] = absent


def _skills(master, draft, groups, ids, new) -> None:
    known = {_norm(t) for g in master.get("skills", []) for t in g["terms"]}
    for group in groups:
        terms = []
        for term in group.get("terms", []):
            if _norm(term) not in known:
                known.add(_norm(term))
                terms.append(term)
        if not terms:
            continue
        target = next((g for g in draft.setdefault("skills", []) if _norm(g["label"]) == _norm(group.get("label"))),
                      None)
        if target is None:
            target = {"id": ids.new(group.get("id") or slug(f"skills-{group.get('label', '')}")),
                      "label": group.get("label") or "Skills", "terms": []}
            draft["skills"].append(target)
        target["terms"].extend(terms)
        new.setdefault("skills", {}).setdefault(target["label"], []).extend(terms)
