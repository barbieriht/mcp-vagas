"""Lista de trabalho pronta (vagas a_aplicar), separando prontas para candidatura das com pendência.

Não depende de MCP. As pendências são deduzidas do registro: modalidade ou senioridade ausentes,
salário não avaliado ou a pesquisar, e o "pending" registrado na candidatura.
"""

from typing import Any

from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore, _related
from vagas.resume_validate import strings, term_set

MISSING_SHOWN = 6


def _pendencies(app: dict[str, Any]) -> list[str]:
    found = []
    if not app.get("work_mode"):
        found.append("modalidade")
    if not app.get("seniority"):
        found.append("senioridade")
    evaluation = app.get("salary_evaluation")
    if not evaluation:
        found.append("salário não avaliado")
    elif evaluation.get("decision") == "pesquisar":
        found.append("pesquisa salarial")
    if app.get("pending"):
        found.append(app["pending"])
    return found


def build_work_list(repo: Repo, resumes: ResumeStore) -> dict[str, Any]:
    try:
        corpus = term_set(strings(resumes.get_master_resume()["resume"]))
    except VagasError:
        corpus = set()
    ready, pending = [], []
    for app in repo.list_applications(status="a_aplicar")["applications"]:
        evaluation = app.get("salary_evaluation") or {}
        missing = (app.get("match_terms") or {}).get("missing", [])
        row = {
            "id": app["id"], "company": app["company"], "role": app["role"], "work_mode": app.get("work_mode"),
            "contract": app.get("contract"),
            "location": app.get("location"), "seniority": app.get("seniority"), "match_score": app.get("match_score"),
            "missing": missing[:MISSING_SHOWN], "related": _related(missing, corpus) if corpus else {},
            "value_to_inform": evaluation.get("value_to_inform") if evaluation.get("decision") == "aplicar" else None,
            "salary_market": app.get("salary_market"), "salary_rule": app.get("salary_rule"),
            "salary_basis": evaluation.get("basis"), "url": app.get("url"), "pending": _pendencies(app),
        }
        (pending if row["pending"] else ready).append(row)
    return {"ready": ready, "pending": pending, "counts": {"ready": len(ready), "pending": len(pending)}}
