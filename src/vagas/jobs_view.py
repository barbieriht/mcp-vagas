"""Vagas registradas, vistas pelo painel: lista com filtros, contagens por status e detalhe. Não depende de HTTP.

Usa o que o Repo já oferece (list_applications, get_history); aqui ficam só os filtros que a lista do
painel acrescenta (texto, aderência mínima), a ordem, a paginação e os rótulos em português.
"""

import re
import sqlite3
from datetime import date
from typing import Any

from vagas.models import SOURCES, STATUSES
from vagas.normalize import normalize_text
from vagas.repo import Repo, VagasError

STATUS_LABELS = {
    "a_aplicar": "A aplicar", "aplicada": "Aplicada", "pendente_usuario": "Pendente com você", "rh": "RH",
    "tecnica": "Técnica", "gestor": "Gestor", "proposta": "Proposta", "recusada": "Recusada",
    "desistiu": "Desistiu", "descartada": "Descartada",
}
WORK_MODE_LABELS = {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial"}
SOURCE_LABELS = {"linkedin": "LinkedIn", "gupy": "Gupy", "indeed": "Indeed", "glassdoor": "Glassdoor",
                 "outro": "Outro site"}
_LIGHT = ("id", "company", "role", "url", "status", "source", "location", "work_mode", "seniority", "match_score",
          "salary_ask", "pending", "discard_reason", "created_at", "updated_at", "last_event_at", "search_id")


def _safe_url(url: Any) -> str | None:
    """Só links http(s) viram link na página."""
    return url if isinstance(url, str) and re.match(r"^https?://", url, re.IGNORECASE) else None


def _light(app: dict[str, Any]) -> dict[str, Any]:
    item = {key: app.get(key) for key in _LIGHT}
    item["url"] = _safe_url(item["url"])
    item["status_label"] = STATUS_LABELS.get(app["status"], app["status"])
    item["source_label"] = SOURCE_LABELS.get(app["source"], app["source"])
    item["work_mode"] = WORK_MODE_LABELS.get(item["work_mode"], item["work_mode"])
    return item


def _int(value: Any, name: str, low: int, high: int) -> int:
    try:
        number = int(str(value).strip())
    except ValueError:
        number = None
    if number is None or not low <= number <= high:
        raise VagasError(f"{name} inválida: {value!r} (use um número de {low} a {high}).")
    return number


def list_jobs(conn: sqlite3.Connection, filters: dict[str, Any]) -> dict[str, Any]:
    """filters (texto, como vêm da URL): status, source, since (AAAA-MM-DD), min_score, text, only_pending,
    order ("aderencia" ou "recentes"), page, per_page."""
    status = filters.get("status") or None
    if status and status not in STATUSES:
        raise VagasError(f"status desconhecido: {status!r}. Use um de: {', '.join(STATUSES)}.")
    source = filters.get("source") or None
    if source and source not in SOURCES:
        raise VagasError(f"site desconhecido: {source!r}. Use um de: {', '.join(SOURCES)}.")
    since = filters.get("since") or None
    if since:
        try:
            date.fromisoformat(since)
        except ValueError:
            raise VagasError(f"data inválida: {since!r} (use AAAA-MM-DD).") from None
    min_score = _int(filters["min_score"], "aderência mínima", 0, 100) if filters.get("min_score") else None
    page = _int(filters.get("page") or 1, "página", 1, 100000)
    per_page = _int(filters.get("per_page") or 50, "itens por página", 1, 200)
    only_pending = str(filters.get("only_pending") or "").lower() in ("1", "true", "sim", "on")

    rows = Repo(conn).list_applications(status=status, only_pending=only_pending, source=source,
                                        since=since)["applications"]
    if text := normalize_text(str(filters.get("text") or "")).strip():
        words = text.split()
        rows = [r for r in rows if all(w in normalize_text(f"{r['role']} {r['company']} {r.get('location') or ''}")
                                       for w in words)]
    if min_score is not None:
        rows = [r for r in rows if r.get("match_score") is not None and r["match_score"] >= min_score]
    order = filters.get("order") or ("aderencia" if status == "a_aplicar" else "recentes")
    if order == "aderencia":
        rows = sorted(rows, key=lambda r: (r.get("match_score") is None, -(r.get("match_score") or 0)))
    elif order != "recentes":
        raise VagasError(f"ordem desconhecida: {order!r} (use aderencia ou recentes).")

    counts = {s: 0 for s in STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM applications GROUP BY status"):
        counts[row["status"]] = row["n"]
    pages = max(1, -(-len(rows) // per_page))
    start = (page - 1) * per_page
    return {"items": [_light(r) for r in rows[start:start + per_page]], "total": len(rows), "page": page,
            "pages": pages, "counts": counts, "order": order,
            "statuses": [{"value": s, "label": STATUS_LABELS[s]} for s in STATUSES],
            "sources": [{"value": s, "label": SOURCE_LABELS[s]} for s in SOURCES]}


def job_detail(conn: sqlite3.Connection, application_id: int) -> dict[str, Any]:
    """Vaga completa: dados, descrição, avaliação salarial, termos da aderência, linha do tempo e currículos."""
    from vagas.resume_extract import windows_path

    history = Repo(conn).get_history(application_id)
    app = {**history["application"]}
    app["url"] = _safe_url(app.get("url"))
    app["status_label"] = STATUS_LABELS.get(app["status"], app["status"])
    app["source_label"] = SOURCE_LABELS.get(app["source"], app["source"])
    app["work_mode"] = WORK_MODE_LABELS.get(app.get("work_mode"), app.get("work_mode"))
    events = [{**e, "to_label": STATUS_LABELS.get(e["to_status"], e["to_status"]),
               "from_label": STATUS_LABELS.get(e["from_status"], e["from_status"]) if e["from_status"] else None}
              for e in history["events"]]
    resumes = [{**r, "windows_path": windows_path(r["pdf_path"])} for r in history["resumes"]]
    return {"application": app, "events": events, "resumes": resumes}
