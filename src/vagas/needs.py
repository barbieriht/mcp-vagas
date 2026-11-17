"""O que a triagem não decidiu (needs), gravado na candidatura como [{kind, detail}] em JSON. Não depende de MCP.

Cada tipo sai sozinho quando o registro passa a responder por ele: modalidade com work_mode, senioridade com
seniority, local com a vaga remota, aderencia com match_score, cargo e salario com uma avaliação salarial feita,
pesquisa_salarial com uma avaliação que não pede mais pesquisa. afirmativa só sai pelo julgamento (descarte).
"""

from typing import Any

from vagas.models import NEED_KINDS


def _evaluated(app: dict[str, Any]) -> bool:
    evaluation = app.get("salary_evaluation")
    return bool(evaluation) and evaluation.get("decision") != "pesquisar"


_RESOLVED = {
    "modalidade": lambda app: app.get("work_mode") is not None,
    "senioridade": lambda app: app.get("seniority") is not None,
    "local": lambda app: app.get("work_mode") == "remoto",
    "aderencia": lambda app: app.get("match_score") is not None,
    "cargo": _evaluated,
    "salario": _evaluated,
    "pesquisa_salarial": lambda app: _evaluated(app) and not app["salary_evaluation"].get("needs_research"),
}


def stored(needs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Na forma gravada: só os tipos conhecidos, cada um uma vez, com kind e detail (sem as consultas prontas,
    que evaluate_salary refaz)."""
    seen, rows = set(), []
    for need in needs:
        kind = need.get("kind")
        if kind in NEED_KINDS and kind not in seen:
            seen.add(kind)
            rows.append({"kind": kind, **({"detail": need["detail"]} if need.get("detail") else {})})
    return rows


def unresolved(needs: list[dict[str, Any]] | None, app: dict[str, Any]) -> list[dict[str, Any]]:
    """Os needs que o registro (com salary_evaluation já lido do JSON) ainda não resolve."""
    return [n for n in needs or [] if not _RESOLVED.get(n["kind"], lambda _: False)(app)]


def kinds(needs: list[dict[str, Any]] | None) -> list[str]:
    return [n["kind"] for n in needs or []]
