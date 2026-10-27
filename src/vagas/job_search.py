"""Histórico de buscas de vagas feitas pelo modelo, para não repetir a mesma busca à toa. Não depende de MCP."""

import json
import os
import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any

from vagas.models import SOURCES
from vagas.normalize import normalize_text
from vagas.repo import VagasError, _require_choice, _require_text, _utcnow

DEFAULT_MIN_HOURS = 24


def _min_hours() -> float:
    env = os.environ.get("VAGAS_JOB_SEARCH_MIN_HOURS")
    return float(env) if env else DEFAULT_MIN_HOURS


def _location_norm(location: str | None) -> str | None:
    return normalize_text(location) if location and location.strip() else None


class JobSearchStore:
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = _utcnow):
        self.conn = conn
        self.now = now
        self.min_hours = _min_hours()

    def save_job_search(
        self,
        query: str,
        source: str,
        results_count: int,
        location: str | None = None,
        filters: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        query = _require_text("query", query)
        _require_choice("source", source, SOURCES)
        if results_count < 0:
            raise VagasError("'results_count' não pode ser negativo.")
        location = location.strip() if location and location.strip() else None
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO job_searches (query, query_norm, source, location, location_norm, filters,
                                          results_count, searched_at, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (query, normalize_text(query), source, location, _location_norm(location),
                 json.dumps(filters, ensure_ascii=False) if filters is not None else None,
                 results_count, self.now(), note),
            )
        return {"search_id": cursor.lastrowid}

    def find_job_search(self, query: str, source: str, location: str | None = None) -> dict[str, Any]:
        query = _require_text("query", query)
        _require_choice("source", source, SOURCES)
        row = self.conn.execute(
            """
            SELECT id, query, source, location, filters, results_count, searched_at, note
            FROM job_searches
            WHERE query_norm = ? AND source = ? AND location_norm IS ?
            ORDER BY searched_at DESC, id DESC LIMIT 1
            """,
            (normalize_text(query), source, _location_norm(location)),
        ).fetchone()
        if row is None:
            return {"search": None, "recent": False, "hours_since": None, "min_hours": self.min_hours}
        search = dict(row)
        search["filters"] = json.loads(search["filters"]) if search["filters"] else None
        elapsed = datetime.fromisoformat(self.now()) - datetime.fromisoformat(search["searched_at"])
        hours = elapsed.total_seconds() / 3600
        return {"search": search, "recent": hours < self.min_hours, "hours_since": round(hours, 2),
                "min_hours": self.min_hours}
