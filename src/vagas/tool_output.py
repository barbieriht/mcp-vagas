"""Forma das respostas e definições das tools: tudo aqui entra no contexto do modelo a cada chamada.

A candidatura completa (com a descrição da vaga, de milhares de caracteres, e a avaliação salarial
inteira) sai só em get_history; os demais retornos trazem a versão enxuta, sem campos vazios.
"""

import functools
import json
from collections.abc import Callable
from typing import Any

import pydantic_core
from mcp.types import CallToolResult, TextContent

# Colunas internas (formas normalizadas para deduplicar) e o texto da vaga: nunca ajudam a decidir o passo seguinte.
_RECORD_HIDDEN = ("description", "company_norm", "url_canonical")
# Detalhes que get_history traz; listas e buscas não precisam deles.
_SUMMARY_HIDDEN = (*_RECORD_HIDDEN, "salary_evaluation", "match_terms")
def _is_empty(value: Any) -> bool:
    return value is None or isinstance(value, list | dict) and not value


def without_empty(row: dict[str, Any]) -> dict[str, Any]:
    """Tira os campos nulos, listas e objetos vazios (0, False e "" ficam: são valores)."""
    return {key: value for key, value in row.items() if not _is_empty(value)}


def application_record(application: dict[str, Any]) -> dict[str, Any]:
    """Candidatura como volta de uma gravação ou triagem: sem a descrição e sem campos vazios."""
    return without_empty({k: v for k, v in application.items() if k not in _RECORD_HIDDEN})


def application_summary(application: dict[str, Any]) -> dict[str, Any]:
    """Linha de lista ou busca: o necessário para escolher a candidatura e o passo seguinte."""
    return without_empty({k: v for k, v in application.items() if k not in _SUMMARY_HIDDEN})


def optional_not_nullable(node: Any) -> Any:
    """Parâmetro opcional com padrão None vira só o tipo, sem `anyOf [..., null]` nem `"default": null`:
    omitir já quer dizer "sem valor" (e o servidor continua aceitando null explícito)."""
    if isinstance(node, list):
        return [optional_not_nullable(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            required = set(node.get("required", ()))
            result[key] = {name: _not_nullable(optional_not_nullable(prop)) if name not in required
                           else optional_not_nullable(prop) for name, prop in value.items()}
        elif key in ("default", "enum", "const", "examples"):
            result[key] = value
        else:
            result[key] = optional_not_nullable(value)
    return result


def _not_nullable(prop: Any) -> Any:
    if not isinstance(prop, dict) or "default" not in prop or prop["default"] is not None:
        return prop
    prop = {k: v for k, v in prop.items() if k != "default"}
    branches = prop.get("anyOf")
    if isinstance(branches, list) and len(branches) == 2 and {"type": "null"} in branches:
        [other] = [b for b in branches if b != {"type": "null"}]
        prop = {**{k: v for k, v in prop.items() if k != "anyOf"}, **other}
    return prop


def compact_result(fn: Callable[..., Any]) -> Callable[..., CallToolResult]:
    """O texto da resposta (lido por clientes que ignoram structuredContent) vai em JSON compacto,
    não no JSON indentado do SDK, que custa de 10% a 50% a mais. O conteúdo estruturado é o mesmo."""
    @functools.wraps(fn)
    def call(**kwargs: Any) -> CallToolResult:
        data = json.loads(pydantic_core.to_json(fn(**kwargs), fallback=str))
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=data)
    return call


def config_view(described: dict[str, Any]) -> dict[str, Any]:
    """get_config é chamado antes de cada fluxo: a descrição de cada chave só acompanha as que ainda
    precisam ser perguntadas, e o nome da variável de ambiente só quando é ela que define o valor."""
    pending = set(described["needs_setup"])

    def entry(key: str, setting: dict[str, Any]) -> dict[str, Any]:
        hidden = {"description"} if key not in pending else set()
        if setting.get("source") != "env":
            hidden.add("env")
        return without_empty({k: v for k, v in setting.items() if k not in hidden})

    return {**described, "settings": {key: entry(key, s) for key, s in described["settings"].items()}}
