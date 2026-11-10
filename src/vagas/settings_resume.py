"""Seção "Currículo geral" do painel: o rascunho (ou a versão aprovada) por seção, editável.

Grava pelo mesmo ResumeStore.save_master_draft do chat: o rascunho continua sendo o YAML editável,
validado pelo MasterResume e sem anotações sobre as fontes. O painel cria os ids que faltam (itens e
parágrafos novos) e preserva os existentes, dos quais os currículos personalizados dependem. Campos que
o painel não mostra (ex.: title_aliases) voltam como vieram. Não depende de HTTP.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from vagas.normalize import normalize_text
from vagas.repo import VagasError

TITLE = "Currículo geral"
START_HINT = ("Ainda não há currículo geral. Peça ao Claude: \"monte meu currículo geral a partir do meu PDF e do "
              "meu LinkedIn\". Depois, revise e edite aqui.")


def _f(key: str, label: str, type: str = "text", **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": type, **extra}


_PARAGRAPHS = _f("paragraphs", "Parágrafos", "list", required=True, add="Adicionar parágrafo",
                 item={"fields": [_f("text", "Texto", "longtext", required=True)], "summary": ["text"]})
_WORK_MODE = _f("work_mode", "Modalidade", "choice",
                choices=[{"value": "remote", "label": "Remoto"}, {"value": "hybrid", "label": "Híbrido"},
                         {"value": "onsite", "label": "Presencial"}])
_DATES = [_f("start", "Início", placeholder="Ex.: May 2024"), _f("end", "Fim", placeholder="Vazio ou Present = atual")]

SCHEMA: dict[str, Any] = {"fields": [
    _f("basics", "Dados", "object", fields=[
        _f("name", "Nome", required=True), _f("headline", "Headline"), _f("email", "E-mail"),
        _f("phone", "Telefone"), _f("location", "Local"), _f("links", "Links", "textlist"),
    ]),
    _f("summary", "Resumo", "longtext"),
    _f("experience", "Experiências", "list", add="Adicionar experiência", item={"summary": ["title", "company", "start", "end"], "fields": [
        _f("company", "Empresa", required=True), _f("context", "Contexto (ex.: projeto financiado)"),
        _f("title", "Cargo", required=True), _f("location", "Local"), _WORK_MODE,
        _f("start", "Início", required=True, placeholder="Ex.: May 2024"), _DATES[1], _PARAGRAPHS,
    ]}),
    _f("education", "Formação", "list", add="Adicionar formação", item={"summary": ["degree", "institution"], "fields": [
        _f("institution", "Instituição", required=True), _f("degree", "Grau", required=True),
        _f("field", "Área"), _f("notes", "Observações", "longtext"), *_DATES,
    ]}),
    _f("volunteering", "Voluntariado", "list", add="Adicionar voluntariado", item={"summary": ["role", "organization"], "fields": [
        _f("organization", "Organização", required=True), _f("role", "Função", required=True),
        _f("location", "Local"), _WORK_MODE, *_DATES, {**_PARAGRAPHS, "required": False},
    ]}),
    _f("projects", "Projetos", "list", add="Adicionar projeto", item={"summary": ["name"], "fields": [
        _f("name", "Nome", required=True), _f("link", "Link"), *_DATES, {**_PARAGRAPHS, "required": False},
    ]}),
    _f("publications", "Publicações", "list", add="Adicionar publicação", item={"summary": ["title", "year"], "fields": [
        _f("title", "Título", required=True), _f("venue", "Veículo"), _f("year", "Ano", "int"),
        _f("authors", "Autores"), _f("link", "Link"),
    ]}),
    _f("skills", "Competências", "list", add="Adicionar grupo", item={"summary": ["label"], "fields": [
        _f("label", "Grupo", required=True), _f("terms", "Termos", "textlist", required=True),
    ]}),
    _f("certifications", "Certificações", "list", add="Adicionar grupo", item={"summary": ["label"], "fields": [
        _f("label", "Grupo", required=True),
        _f("items", "Certificados", "list", required=True, add="Adicionar certificado",
           item={"summary": ["name", "year"], "fields": [
               _f("name", "Título (em inglês)", required=True), _f("name_original", "Título original"),
               _f("provider", "Emissor"), _f("year", "Ano", "int"),
               _f("issued", "Emissão", placeholder="AAAA-MM"), _f("credential_id", "ID da credencial"),
               _f("link", "Link"), _f("description", "Descrição", "longtext"),
           ]}),
    ]}),
    _f("languages", "Idiomas do currículo", "list", add="Adicionar idioma", item={"summary": ["name", "level"], "fields": [
        _f("name", "Idioma", required=True), _f("level", "Nível", required=True),
        _f("note", "Complemento (ex.: certificação)"),
    ]}),
]}

# Prefixo do id e campos que dão o nome do id, por seção (ids existentes nunca mudam).
_ID_RULES = {"experience": ("exp", ("company", "title")), "education": ("edu", ("institution", "degree")),
             "volunteering": ("vol", ("organization", "role")), "projects": ("proj", ("name",)),
             "publications": ("pub", ("title",)), "skills": ("skill", ("label",)),
             "certifications": ("cert", ("label",))}


def _draft_path(db_path: Path | str | None) -> Path:
    from vagas.resume_repo import default_draft_path

    return Path(default_draft_path(db_path))


def _fingerprint(path: Path) -> str:
    from vagas.resume_repo import _text_hash

    return _text_hash(path.read_text(encoding="utf-8")) if path.exists() else ""


def load_resume(db_path: Path | str | None) -> dict[str, Any]:
    from vagas.db import connect
    from vagas.resume_repo import ResumeStore

    path = _draft_path(db_path)
    base = {"key": "resume", "title": TITLE, "file": str(path), "groups": [], "pending": [], "schema": SCHEMA}
    if path.exists():
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            return {**base, "error": f"O rascunho {path} não é um YAML válido ({exc}). Corrija o arquivo à mão."}
        return {**base, "origin": "draft", "value": value, "hash": _fingerprint(path), "approval": _approval(db_path)}
    conn = connect(db_path) if db_path is not None else connect()
    try:
        approved = ResumeStore(conn, path).get_master_resume()
    except VagasError:
        return {**base, "error": START_HINT}
    finally:
        conn.close()
    return {**base, "origin": "approved", "value": approved["resume"], "hash": "",
            "approved_at": approved["approved_at"],
            "approval": {"can_approve": False, "reason": "Não há rascunho: edite e salve para criar um.",
                         "changes": [], "review": []}}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_text(text)).strip("-") or "item"


def _clean(value: Any) -> Any:
    """Tira espaços e remove campos vazios ("" some; listas vazias ficam, para a validação apontá-las)."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not (isinstance(v, str) and not v.strip()) and v is not None}
    if isinstance(value, list):
        return [_clean(v) for v in value if not (isinstance(v, str) and not v.strip())]
    return value.strip() if isinstance(value, str) else value


def _all_ids(data: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(data, dict):
        if isinstance(data.get("id"), str):
            found.add(data["id"])
        for value in data.values():
            found |= _all_ids(value)
    elif isinstance(data, list):
        for value in data:
            found |= _all_ids(value)
    return found


def _unique(base: str, used: set[str]) -> str:
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    used.add(candidate)
    return candidate


def _paragraph_ids(item: dict[str, Any], used: set[str]) -> None:
    for paragraph in item.get("paragraphs") or []:
        if isinstance(paragraph, dict) and not paragraph.get("id"):
            n = 1
            while f"{item['id']}-p{n}" in used:
                n += 1
            paragraph["id"] = f"{item['id']}-p{n}"
            used.add(paragraph["id"])


def _assign_ids(data: dict[str, Any]) -> None:
    used = _all_ids(data)
    for section, (prefix, keys) in _ID_RULES.items():
        for item in data.get(section) or []:
            if not isinstance(item, dict):
                continue
            if not item.get("id"):
                name = "-".join(_slug(str(item.get(k, ""))) for k in keys if item.get(k))
                item["id"] = _unique(f"{prefix}-{name or 'item'}", used)
            _paragraph_ids(item, used)
            for cert in item.get("items") or [] if section == "certifications" else []:
                if isinstance(cert, dict) and not cert.get("id"):
                    cert["id"] = _unique(f"{item['id']}-{_slug(str(cert.get('name', 'item')))}", used)


_MESSAGES = {"missing": "Campo obrigatório.", "string_too_short": "Campo obrigatório.",
             "too_short": "Inclua pelo menos um item.", "int_parsing": "Informe um número inteiro.",
             "int_type": "Informe um número inteiro.", "literal_error": "Escolha uma das opções.",
             "extra_forbidden": "Campo desconhecido.", "list_type": "Envie uma lista.", "dict_type": "Envie um objeto."}


def _errors(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for error in exc.errors():
        loc = [str(part) for part in error["loc"]]
        key = ".".join(["resume", *loc])
        if error["type"] == "string_pattern_mismatch":
            message = "Use AAAA-MM ou AAAA." if loc and loc[-1] == "issued" else "Formato inválido."
        else:
            message = _MESSAGES.get(error["type"], error["msg"].removeprefix("Value error, "))
        errors.setdefault(key, message)
    return errors


@dataclass
class ResumeChange:
    db_path: Path | str | None
    data: dict[str, Any]

    def run(self) -> None:
        from vagas.db import connect
        from vagas.resume_repo import ResumeStore

        conn = connect(self.db_path) if self.db_path is not None else connect()
        try:
            ResumeStore(conn, _draft_path(self.db_path)).save_master_draft(self.data, overwrite=True)
        finally:
            conn.close()


def plan_resume(values: Any, db_path: Path | str | None) -> tuple[ResumeChange | None, dict[str, str]]:
    from vagas.resume_model import MasterResume
    from vagas.resume_repo import SOURCE_NOTES_HELP
    from vagas.resume_validate import source_note_problems

    if not isinstance(values, dict) or not isinstance(values.get("data"), dict):
        return None, {"resume": "Envie {data: currículo, hash: impressão do rascunho carregado}."}
    if values.get("hash", "") != _fingerprint(_draft_path(db_path)):
        return None, {"resume": "O rascunho mudou depois que você abriu o painel (o Claude ou outra janela o "
                                "gravou). Recarregue a página para ver a versão nova antes de editar."}
    data = _clean(values["data"])
    _assign_ids(data)
    try:
        resume = MasterResume.model_validate(data)
    except ValidationError as exc:
        return None, _errors(exc)
    clean = resume.as_data()
    if problems := source_note_problems(clean):
        return None, {"resume": f"Estes campos {SOURCE_NOTES_HELP}: " + "; ".join(problems)}
    return ResumeChange(db_path, clean), {}


# --- diferenças com a versão aprovada e aprovação ----------------------------------------------------

_LABEL_KEYS = ("title", "role", "degree", "name", "label", "company", "organization", "institution")


def _label(item: dict[str, Any]) -> str:
    parts = [str(item[k]) for k in _LABEL_KEYS if item.get(k)][:2]
    return " · ".join(parts) or str(item.get("id", ""))


def _key_of(item: dict[str, Any]) -> str:
    return str(item.get("id") or normalize_text(str(item.get("name", ""))))


def draft_changes(store: Any) -> list[dict[str, Any]]:
    """O que o rascunho muda em relação à versão aprovada: por seção, itens novos, removidos e alterados
    (com os campos). Sem versão aprovada, tudo é novo."""
    from vagas.resume_model import MasterResume

    draft = MasterResume.model_validate(store._read_draft()).as_data()
    try:
        approved = store.get_master_resume()["resume"]
    except VagasError:
        approved = {}
    changes: list[dict[str, Any]] = []
    for key in ("basics", "summary"):
        old, new = approved.get(key), draft.get(key)
        if old == new:
            continue
        if isinstance(old, dict) or isinstance(new, dict):
            fields = sorted(k for k in set(old or {}) | set(new or {}) if (old or {}).get(k) != (new or {}).get(k))
        else:
            fields = [key]
        changes.append({"section": key, "kind": "changed", "fields": fields, "label": ""})
    for section in ("experience", "education", "volunteering", "projects", "publications", "skills",
                    "certifications", "languages"):
        old = {_key_of(i): i for i in approved.get(section, [])}
        new = {_key_of(i): i for i in draft.get(section, [])}
        for key, item in new.items():
            entry = {"section": section, "id": item.get("id"), "label": _label(item)}
            if key not in old:
                changes.append({**entry, "kind": "added"})
            elif item != old[key]:
                fields = sorted(k for k in set(item) | set(old[key]) if item.get(k) != old[key].get(k))
                changes.append({**entry, "kind": "changed", "fields": fields})
        for key, item in old.items():
            if key not in new:
                changes.append({"section": section, "id": item.get("id"), "label": _label(item), "kind": "removed"})
    return changes


def _approval(db_path: Path | str | None) -> dict[str, Any]:
    from pydantic import ValidationError as _Invalid

    from vagas.db import connect
    from vagas.resume_repo import ResumeStore

    conn = connect(db_path) if db_path is not None else connect()
    try:
        store = ResumeStore(conn, _draft_path(db_path))
        try:
            changes = draft_changes(store)
            review = store.draft_review() or []
        except (VagasError, _Invalid) as exc:
            return {"can_approve": False, "changes": [], "review": [],
                    "reason": f"O rascunho tem erros: corrija e salve antes de aprovar. ({str(exc)[:300]})"}
    finally:
        conn.close()
    if not changes:
        return {"can_approve": False, "changes": [], "review": review,
                "reason": "Nenhuma diferença em relação à versão aprovada."}
    return {"can_approve": True, "changes": changes, "review": review, "reason": ""}


def approve(db_path: Path | str | None, fingerprint: str) -> dict[str, Any]:
    """Aprova o rascunho que o usuário viu no painel (mesma impressão digital), pelo approve_master."""
    from vagas.db import connect
    from vagas.resume_repo import ResumeStore

    if not isinstance(fingerprint, str) or fingerprint != _fingerprint(_draft_path(db_path)) or not fingerprint:
        raise VagasError("O rascunho mudou depois que você abriu o painel (ou não existe mais). Recarregue a "
                         "página, confira as diferenças e aprove de novo.")
    conn = connect(db_path) if db_path is not None else connect()
    try:
        return ResumeStore(conn, _draft_path(db_path)).approve_master()
    finally:
        conn.close()
