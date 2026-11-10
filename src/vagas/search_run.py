"""Busca em lote: as buscas sugeridas e a triagem de cada vaga nova, numa execução só. Não depende de MCP.

Roda em segundo plano (python -m vagas.search_run run --run-id N), disparada pela tool start_search_run,
e grava progresso e resumo na tabela search_runs; get_search_run lê. A LLM fica só com o que exige
julgamento (os needs de cada vaga). Os intervalos por site são os do acesso HTTP (VAGAS_SITE_MIN_SECONDS,
VAGAS_LINKEDIN_JOBS_MIN_SECONDS); se o LinkedIn limitar, a execução espera uma vez e, se continuar
limitado, segue sem ele.
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import traceback
from collections.abc import Callable
from typing import Any

from vagas import system
from vagas.job_board import MAX_PAGES, SEARCHABLE, JobBoard
from vagas.repo import VagasError, _utcnow

log = logging.getLogger(__name__)
DEFAULTS = {"sources": list(SEARCHABLE), "linkedin_remote_only": True, "max_pages": 1}
LIMIT_WAIT_SECONDS = 180


def _alive(pid: int | None) -> bool:
    return system.process_alive(pid)


def check_params(params: dict[str, Any] | None) -> dict[str, Any]:
    params = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if v is not None}}
    unknown = set(params) - set(DEFAULTS)
    if unknown:
        raise VagasError(f"Parâmetro desconhecido: {', '.join(sorted(unknown))}. Use: {', '.join(DEFAULTS)}.")
    if not params["sources"] or any(s not in SEARCHABLE for s in params["sources"]):
        raise VagasError(f"'sources' deve ter um ou mais entre: {', '.join(SEARCHABLE)}.")
    if not isinstance(params["max_pages"], int) or not 1 <= params["max_pages"] <= MAX_PAGES:
        raise VagasError(f"'max_pages' deve ser um número de 1 a {MAX_PAGES}.")
    return params


class SearchRunStore:
    def __init__(self, conn: sqlite3.Connection, now: Callable[[], str] = _utcnow):
        self.conn = conn
        self.now = now

    def create(self, params: dict[str, Any] | None) -> int:
        params = check_params(params)
        for row in self.conn.execute("SELECT id, pid FROM search_runs WHERE status = 'running'").fetchall():
            if _alive(row["pid"]) or row["pid"] is None:
                raise VagasError(f"Já há uma busca em lote em andamento (execução {row['id']}); acompanhe com "
                                 "get_search_run.")
            self._finish(row["id"], "interrompida", error="O processo da busca terminou sem concluir.")
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO search_runs (params, status, started_at) VALUES (?, 'running', ?)",
                (json.dumps(params, ensure_ascii=False), self.now()))
        return cursor.lastrowid

    def set_pid(self, run_id: int, pid: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE search_runs SET pid = ? WHERE id = ?", (pid, run_id))

    def progress(self, run_id: int, progress: dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute("UPDATE search_runs SET progress = ? WHERE id = ?",
                              (json.dumps(progress, ensure_ascii=False), run_id))

    def finish(self, run_id: int, summary: dict[str, Any]) -> None:
        self._finish(run_id, "done", summary=summary)

    def fail(self, run_id: int, error: str, summary: dict[str, Any] | None = None) -> None:
        self._finish(run_id, "error", summary=summary, error=error)

    def _finish(self, run_id: int, status: str, summary: dict[str, Any] | None = None, error: str | None = None):
        with self.conn:
            self.conn.execute(
                "UPDATE search_runs SET status = ?, summary = COALESCE(?, summary), error = ?, finished_at = ? "
                "WHERE id = ?",
                (status, json.dumps(summary, ensure_ascii=False) if summary is not None else None, error, self.now(),
                 run_id))

    def get(self, run_id: int | None = None) -> dict[str, Any]:
        if run_id is None:
            row = self.conn.execute("SELECT * FROM search_runs ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                raise VagasError("Nenhuma busca em lote foi executada ainda; comece com start_search_run.")
        else:
            row = self.conn.execute("SELECT * FROM search_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise VagasError(f"Busca em lote {run_id} não existe.")
        run = dict(row)
        if run["status"] == "running" and run["pid"] and not _alive(run["pid"]):
            self._finish(run["id"], "interrompida", error="O processo da busca terminou sem concluir.")
            return self.get(run["id"])
        for field in ("params", "progress", "summary"):
            run[field] = json.loads(run[field]) if run[field] else None
        return run


class SearchRunner:
    def __init__(self, conn: sqlite3.Connection, board: JobBoard, triage: Any,
                 limit_wait_seconds: float = LIMIT_WAIT_SECONDS):
        self.store = SearchRunStore(conn)
        self.board = board
        self.triage = triage
        self.limit_wait = limit_wait_seconds

    def run(self, run_id: int) -> dict[str, Any]:
        params = self.store.get(run_id)["params"]
        summary = _empty_summary()
        try:
            self._run(run_id, params, summary)
        except Exception as exc:  # erro inesperado: guarda o que já foi feito
            log.exception("busca em lote %s falhou", run_id)
            summary["errors"].append({"step": "run", "error": f"{type(exc).__name__}: {exc}"})
            self.store.fail(run_id, f"{type(exc).__name__}: {exc}", summary)
            return summary
        self.store.finish(run_id, summary)
        return summary

    def _run(self, run_id: int, params: dict[str, Any], summary: dict[str, Any]) -> None:
        suggestions = self.board.suggest_job_searches()["searches"]
        wanted = [s for s in suggestions if s["source"] in params["sources"]
                  and not (s["source"] == "linkedin" and params["linkedin_remote_only"] and s["location"])]
        plan = [s for s in wanted if not s["recent"]]
        summary["searches"]["skipped"] = len(wanted) - len(plan)
        progress = {"searches_total": len(plan), "searches_done": 0, "jobs_total": 0, "jobs_done": 0, "current": None}
        queue: list[tuple[str, int, str]] = []
        seen: set[str] = set()
        blocked: set[str] = set()

        for search in plan:
            source = search["source"]
            progress["current"] = f"busca {source}: {search['query']} ({search['location'] or 'sem local'})"
            self.store.progress(run_id, progress)
            if source in blocked:
                summary["searches"]["errors"] += 1
            else:
                result = self._search(search, params, summary, blocked)
                if result is not None:
                    summary["searches"]["run"] += 1
                    for job in result["results"]:
                        if job["url"] in seen:
                            continue
                        seen.add(job["url"])
                        summary["jobs"]["found"] += 1
                        if job["registered"]:
                            summary["jobs"]["already_registered"] += 1
                        else:
                            queue.append((job["url"], result["search_id"], source))
            progress["searches_done"] += 1
            progress["jobs_total"] = len(queue)
            self.store.progress(run_id, progress)

        for url, search_id, source in queue:
            progress["current"] = f"triagem: {url}"
            self.store.progress(run_id, progress)
            if source in blocked and source == "linkedin":
                summary["errors"].append({"step": "triage", "url": url, "error": "LinkedIn limitado; triar depois."})
            else:
                self._triage(url, search_id, source, summary, blocked)
            progress["jobs_done"] += 1
            self.store.progress(run_id, progress)
        progress["current"] = None
        self.store.progress(run_id, progress)

    def _limited(self, source: str, call: Callable[[], Any], blocked: set[str]) -> Any:
        """Chama; se o site limitar, espera uma vez e tenta de novo; se continuar, marca o site como bloqueado."""
        try:
            return call()
        except VagasError as exc:
            if "limitou" not in str(exc):
                raise
            time.sleep(self.limit_wait)
            try:
                return call()
            except VagasError as again:
                if "limitou" in str(again):
                    blocked.add(source)
                raise

    def _search(self, search, params, summary, blocked) -> dict[str, Any] | None:
        filters = {**search["filters"], "max_pages": params["max_pages"]}
        try:
            return self._limited(search["source"], lambda: self.board.search_jobs(
                search["query"], search["source"], search["location"], filters), blocked)
        except VagasError as exc:
            summary["searches"]["errors"] += 1
            summary["errors"].append({"step": "search", "source": search["source"], "query": search["query"],
                                      "location": search["location"], "error": str(exc)})
            return None

    def _triage(self, url, search_id, source, summary, blocked) -> None:
        try:
            result = self._limited(source, lambda: self.triage.triage_job(url, search_id=search_id), blocked)
        except VagasError as exc:
            summary["errors"].append({"step": "triage", "url": url, "error": str(exc)})
            return
        summary["jobs"]["triaged"] += 1
        decision = result["decision"]
        summary["decisions"][decision] = summary["decisions"].get(decision, 0) + 1
        app = result["application"] or {}
        posting = result["posting"] or {}
        kinds = [n["kind"] for n in result["needs"]]
        for kind in kinds:
            summary["needs"].setdefault(kind, []).append(app.get("id") or url)
        if decision == "a_aplicar":
            salary = result["salary"] or {}
            summary["a_aplicar"].append({
                "id": app["id"], "company": app["company"], "role": app["role"], "work_mode": app["work_mode"],
                "location": app["location"], "match_score": app["match_score"], "url": app["url"],
                "value_to_inform": salary.get("value_to_inform") if salary.get("decision") == "aplicar" else None,
                "needs": kinds})
        elif decision == "descartada":
            summary["descartadas"].append({"id": app["id"], "company": app["company"], "role": app["role"],
                                           "url": app["url"], "reason": app["discard_reason"]})
        elif decision == "possivel_duplicata":
            summary["possiveis_duplicatas"].append({
                "company": posting.get("company"), "title": posting.get("title"), "url": url,
                "location": posting.get("location"), "matches": result["needs"][0].get("matches", [])})


def _empty_summary() -> dict[str, Any]:
    return {"searches": {"run": 0, "skipped": 0, "errors": 0},
            "jobs": {"found": 0, "already_registered": 0, "triaged": 0},
            "decisions": {}, "a_aplicar": [], "descartadas": [], "possiveis_duplicatas": [], "needs": {},
            "errors": []}


def default_runner(conn: sqlite3.Connection) -> SearchRunner:
    """Executor com os caminhos padrão (os mesmos do servidor: banco, critérios, política, currículo)."""
    from vagas.config import resolve
    from vagas.resume_repo import default_draft_path
    from vagas.salary_policy import default_policy_path
    from vagas.triage import Triage, default_criteria_path

    board = JobBoard(conn, criteria_path=default_criteria_path(), draft_path=default_draft_path())
    triage = Triage(conn, criteria_path=default_criteria_path(), policy_path=default_policy_path(),
                    draft_path=default_draft_path(), salary_rule=resolve("salary_rule")[0])
    return SearchRunner(conn, board, triage)


def main(argv: list[str] | None = None) -> None:
    from vagas.db import connect

    parser = argparse.ArgumentParser(prog="python -m vagas.search_run", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="executa uma busca em lote já criada (usado por start_search_run)")
    run.add_argument("--run-id", type=int, required=True)
    start = sub.add_parser("start", help="cria e executa uma busca em lote neste terminal")
    start.add_argument("--sources", nargs="+", choices=SEARCHABLE)
    start.add_argument("--linkedin-all-locations", action="store_true")
    start.add_argument("--max-pages", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    conn = connect()
    try:
        if args.command == "start":
            run_id = SearchRunStore(conn).create({"sources": args.sources, "max_pages": args.max_pages,
                                                  "linkedin_remote_only": not args.linkedin_all_locations})
        else:
            run_id = args.run_id
        SearchRunStore(conn).set_pid(run_id, os.getpid())
        summary = default_runner(conn).run(run_id)
        print(json.dumps({"run_id": run_id, "decisions": summary["decisions"], "errors": len(summary["errors"])},
                         ensure_ascii=False))
    except VagasError as exc:
        sys.exit(str(exc))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
