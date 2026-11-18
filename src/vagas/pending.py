"""Pendências estruturadas de uma candidatura: itens {kind, field, options?} ao lado do texto livre (pending).
Não depende de MCP.

Os itens deixam a revisão do lote agrupar o que se repete entre as vagas ("12 vagas aguardam: anexar currículo") e
somem sozinhos quando a resposta entra no perfil (diversidade e resposta aberta). Dado sensível nunca vai num item:
o field é o rótulo do campo, a caixa ou o arquivo, nunca o valor.
"""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from vagas import diversity, generic_questions
from vagas.models import PENDING_KINDS, PendingKind
from vagas.normalize import normalize_text
from vagas.repo import VagasError

LABELS = {"diversidade": "diversidade", "consentimento": "consentimento: marcar caixa",
          "anexo_curriculo": "anexar currículo", "documento_cofre": "documento do cofre",
          "resposta_aberta": "responder", "login": "entrar no site"}
BY_FIELD = {"diversidade", "resposta_aberta", "documento_cofre", "login"}  # agrupados pelo campo, não só pelo tipo
FROM_PROFILE = {"diversidade", "resposta_aberta"}  # resolvidos quando a resposta entra no perfil


class PendingItem(BaseModel):
    """O que falta numa candidatura. field: o rótulo do campo do perfil (o missing_field de resolve_form_answer),
    o texto da caixa, o nome do PDF a anexar, o documento (CPF) ou o site do login; options: as opções vistas."""

    model_config = ConfigDict(extra="forbid")
    kind: PendingKind
    field: str
    options: list[str] | None = None


def key(label: str) -> str:
    """Rótulo comparável: sem acento, maiúscula e pontuação; rótulos antigos de diversidade viram o atual."""
    q = diversity.question(label)
    return " ".join(re.findall(r"[a-z0-9]+", normalize_text(q.label if q else label)))


def clean_items(items: list[Any]) -> list[dict[str, Any]]:
    """Itens validados, na forma gravada. VagasError dizendo o que corrigir."""
    cleaned = []
    for index, raw in enumerate(items):
        item = raw.model_dump(exclude_none=True) if isinstance(raw, BaseModel) else raw
        if not isinstance(item, dict):
            raise VagasError(f"pending_items[{index}] deve ser um objeto {{kind, field, options?}}.")
        kind, field = item.get("kind"), str(item.get("field") or "").strip()
        if kind not in PENDING_KINDS:
            raise VagasError(f"pending_items[{index}].kind inválido: {kind!r}. Valores aceitos: {', '.join(PENDING_KINDS)}.")
        if not field:
            raise VagasError(f"pending_items[{index}].field é obrigatório: o campo, a caixa, o arquivo ou o site.")
        row: dict[str, Any] = {"kind": kind, "field": field}
        options = [str(o).strip() for o in item.get("options") or [] if str(o).strip()]
        if options:
            row["options"] = options
        cleaned.append(row)
    return cleaned


def groups(apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pendências iguais entre as vagas, as mais frequentes primeiro: {kind, field?, label, count, ids}."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for app in apps:
        for item in app.get("pending_items") or []:
            kind = item["kind"]
            field = item["field"] if kind in BY_FIELD else ""
            group = found.setdefault((kind, key(field)), {"kind": kind, **({"field": field} if field else {}),
                                                         "label": f"{LABELS[kind]}: {field}" if field else LABELS[kind],
                                                         "count": 0, "ids": []})
            if app["id"] not in group["ids"]:
                group["ids"].append(app["id"])
                group["count"] += 1
    for group in found.values():
        group["ids"].sort()
    return sorted(found.values(), key=lambda g: (-g["count"], g["label"]))


def answered(profile: dict[str, Any]) -> set[str]:
    """Rótulos (key) dos campos do perfil já respondidos (status ok)."""
    return {key(f["label"]) for s in profile.get("sections") or [] for f in s.get("fields") or [] if f["status"] == "ok"}


def _generic_done(field: str, done: set[str]) -> bool:
    """Item de um campo criado por empresa ("Você trabalha na empresa X?"): o currículo geral responde trabalha e
    trabalhou; a indicação, o campo genérico do perfil."""
    kind = generic_questions.kind(re.sub(r"\s*\(op[cç][oõ]es\b.*$", "", field))
    if kind == generic_questions.REFERRAL:
        return key(generic_questions.REFERRAL_LABEL) in done
    return kind is not None


def unresolved(items: list[dict[str, Any]], done: set[str]) -> list[dict[str, Any]]:
    return [i for i in items if not (i["kind"] in FROM_PROFILE
                                     and (key(i["field"]) in done or _generic_done(i["field"], done)))]
