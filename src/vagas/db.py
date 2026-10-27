"""Conexão com o SQLite, schema e migrações (versionadas por PRAGMA user_version)."""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS = [
    # v1
    """
    CREATE TABLE applications (
        id INTEGER PRIMARY KEY,
        company TEXT NOT NULL,
        company_norm TEXT NOT NULL,
        role TEXT NOT NULL,
        url TEXT,
        url_canonical TEXT UNIQUE,
        source TEXT NOT NULL,
        seniority TEXT,
        work_mode TEXT,
        location TEXT,
        salary_expectation TEXT,
        description TEXT,
        status TEXT NOT NULL,
        pending TEXT,
        discard_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX applications_company_norm ON applications (company_norm);

    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES applications (id),
        at TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        note TEXT
    );
    CREATE INDEX events_application_id ON events (application_id);
    """,
]
LATEST_VERSION = len(MIGRATIONS)


def default_db_path() -> Path:
    if env := os.environ.get("VAGAS_DB"):
        return Path(env)
    return Path.home() / ".local/share/vagas/vagas.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Abre o banco, aplica os PRAGMAs e migra o schema até a versão mais recente."""
    path = Path(path) if path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists() and path.stat().st_size > 0

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn, path, existed)
    return conn


def _migrate(conn: sqlite3.Connection, path: Path, existed: bool) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= LATEST_VERSION:
        return
    if existed:
        _backup(conn, path, version)
    for target, script in enumerate(MIGRATIONS[version:], start=version + 1):
        with conn:
            conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {target}; COMMIT;")
        log.info("Banco migrado para a versão %d", target)


def _backup(conn: sqlite3.Connection, path: Path, version: int) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    target = path.with_name(f"{path.name}.bak-v{version}-{stamp}")
    with sqlite3.connect(target) as copy:
        conn.backup(copy)
    copy.close()
    log.info("Backup do banco antes de migrar: %s", target)
