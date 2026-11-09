"""Seleção inicial do currículo personalizado a partir dos termos da vaga. Não depende de MCP.

Pontua cada parágrafo, item e grupo de skills pelos termos da vaga presentes no currículo ("matched"
de score_job_match) e monta uma TailoredSelection válida: experiências na ordem do currículo, com os
parágrafos que citam os termos primeiro (os sem termos saem, mas cada experiência mantém ao menos um);
voluntariado, projetos e publicações só com o que cita algum termo; até CERT_LIMIT certificações, as que
mais citam os termos; skills com os grupos
e termos da vaga primeiro; formação e idiomas inteiros. A LLM refina (corta, reordena, reescreve em
bullets) e gera com create_tailored_resume.
"""

import re
from typing import Any

from vagas.resume_tailor import CONTINUATION, DEFAULT_ORDER

_PARAGRAPH_SECTIONS = ("experience", "volunteering", "projects")
_OPTIONAL_SECTIONS = ("volunteering", "projects", "publications", "certifications")
CERT_LIMIT = 6
# O que recrutadores procuram por família de cargo: sistemas em produção nas engenharias, análise e experimentos
# em ciência e análise de dados. Esses termos só ajudam a escolher parágrafos; não entram nas skills.
_PRODUCTION = ("production", "deploy", "deployed", "deployment", "AWS", "Lambda", "Terraform", "Docker", "Kubernetes",
               "FastAPI", "API", "APIs", "CI/CD", "MLOps", "monitoring", "serverless", "microservices")
_ANALYSIS = ("analysis", "statistical", "experiment", "experiments", "A/B", "forecasting", "hypothesis",
             "regression", "insights")
ROLE_FOCUS = {"ml_engineer": _PRODUCTION, "ai_engineer": _PRODUCTION, "data_engineer": _PRODUCTION,
              "data_scientist": _ANALYSIS, "data_analyst": _ANALYSIS}


def _count(text: str, terms: list[str]) -> int:
    return sum(1 for t in terms if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, re.I))


def _item_text(item: dict[str, Any]) -> str:
    return " ".join(str(v) for k, v in item.items() if isinstance(v, str) and k != "id")


def suggest_selection(master: dict[str, Any], terms: list[str], label: str | None,
                      role_key: str | None = None) -> dict[str, Any]:
    terms = list(dict.fromkeys(t for t in terms if t and t.strip()))
    focus = [t for t in ROLE_FOCUS.get(role_key or "", ()) if t.lower() not in {x.lower() for x in terms}]
    evidence = " ".join(p["text"] for s in _PARAGRAPH_SECTIONS for item in master.get(s) or []
                        for p in item.get("paragraphs") or [])
    scores: dict[str, dict[str, int]] = {"paragraphs": {}, "items": {}, "skills": {}}
    sections: list[dict[str, Any]] = []

    for section in DEFAULT_ORDER:
        available = master.get(section) or []
        if not available:
            continue
        if not terms or section in ("education", "languages"):
            sections.append({"section": section, "items": None})
            continue
        if section in _PARAGRAPH_SECTIONS:
            picked = _paragraph_items(section, available, terms + focus if section == "experience" else terms,
                                      scores)
        elif section == "skills":
            picked = _skills(available, terms, scores, evidence)
        elif section == "certifications":
            picked = _certifications(available, terms, scores)
        else:
            picked = []
            for item in available:
                scores["items"][item["id"]] = _count(_item_text(item), terms)
                if scores["items"][item["id"]]:
                    picked.append({"id": item["id"]})
        if picked:
            sections.append({"section": section, "items": picked})
        elif section not in _OPTIONAL_SECTIONS:
            sections.append({"section": section, "items": None})

    selection: dict[str, Any] = {"sections": sections}
    if label:
        selection["label"] = label
    note = None if terms else ("Sem termos da vaga presentes no currículo: a seleção traz tudo, na ordem do "
                               "currículo geral; escolha pela leitura da vaga.")
    return {"selection": selection, "scores": scores, "terms": terms, "note": note}


def _paragraph_items(section, available, terms, scores) -> list[dict[str, Any]]:
    picked = []
    for item in available:
        paragraphs = item.get("paragraphs") or []
        ranked = []
        for position, paragraph in enumerate(paragraphs):
            score = _count(paragraph["text"], terms)
            scores["paragraphs"][paragraph["id"]] = score
            ranked.append((-score, position, paragraph["id"]))
        total = sum(scores["paragraphs"][p["id"]] for p in paragraphs)
        scores["items"][item["id"]] = total
        if section != "experience" and total == 0:
            continue
        chosen = [pid for neg, _, pid in ranked if neg < 0]  # na ordem do currículo geral
        if not chosen and paragraphs:
            chosen = [paragraphs[0]["id"]]  # toda experiência aparece, com ao menos o primeiro parágrafo
        first = next((p for p in paragraphs if p["id"] == chosen[0]), None) if chosen else None
        if first is not None and CONTINUATION.match(first["text"]) and paragraphs[0]["id"] not in chosen:
            chosen.insert(0, paragraphs[0]["id"])  # o parágrafo que ele retoma
        pick: dict[str, Any] = {"id": item["id"]}
        if paragraphs:
            pick["paragraphs"] = [{"id": pid} for pid in chosen]
        picked.append(pick)
    return picked


def _skills(groups, terms, scores, evidence: str) -> list[dict[str, Any]]:
    """Grupos com termos da vaga; em cada um, os da vaga primeiro e depois só os que aparecem em alguma
    experiência, voluntariado ou projeto (skill sem comprovação vira lista de palavras-chave)."""
    wanted = {t.lower() for t in terms}
    ranked = []
    for position, group in enumerate(groups):
        hits = [t for t in group["terms"] if t.lower() in wanted or _count(t, terms)]
        scores["skills"][group["id"]] = len(hits)
        if hits:
            rest = [t for t in group["terms"] if t not in hits and _count(evidence, [t])]
            ranked.append((-len(hits), position, {"id": group["id"], "terms": hits + rest}))
    return [pick for _, _, pick in sorted(ranked, key=lambda r: (r[0], r[1]))]


def _certifications(groups, terms, scores) -> list[dict[str, Any]]:
    """As CERT_LIMIT certificações com mais termos da vaga (empate: ordem do currículo), nos seus grupos."""
    ranked = []
    for g, group in enumerate(groups):
        for c, cert in enumerate(group["items"]):
            scores["items"][cert["id"]] = _count(_item_text(cert), terms)
            if scores["items"][cert["id"]]:
                ranked.append((-scores["items"][cert["id"]], g, c, cert["id"]))
    order = {cert_id: n for n, (*_, cert_id) in enumerate(sorted(ranked)[:CERT_LIMIT])}
    picked = []
    for group in groups:
        hits = sorted((cert["id"] for cert in group["items"] if cert["id"] in order), key=order.get)
        if hits:
            picked.append({"id": group["id"], "items": hits})
    return picked
