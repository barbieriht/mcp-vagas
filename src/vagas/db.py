"""Conexão com o SQLite, schema e migrações (versionadas por PRAGMA user_version)."""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from vagas.normalize import canonical_url, normalize_company

log = logging.getLogger(__name__)


def _renormalize_companies(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, company FROM applications").fetchall()
    conn.executemany(
        "UPDATE applications SET company_norm = ? WHERE id = ?",
        [(normalize_company(row[1]), row[0]) for row in rows],
    )

def _recanonicalize_urls(conn: sqlite3.Connection) -> None:
    """Recalcula url_canonical com as regras por plataforma. Se duas candidaturas passam a ter a
    mesma forma canônica, a mais antiga fica com ela e a outra mantém a forma anterior."""
    rows = conn.execute(
        "SELECT id, url, url_canonical FROM applications WHERE url IS NOT NULL ORDER BY id"
    ).fetchall()
    taken = {row[2] for row in rows if row[2]}
    for application_id, url, old in rows:
        new = canonical_url(url)
        if new == old:
            continue
        if new in taken:
            log.warning("Candidatura %d: URL %s coincide com outra já registrada; mantida a forma anterior",
                        application_id, new)
            continue
        conn.execute("UPDATE applications SET url_canonical = ? WHERE id = ?", (new, application_id))
        taken.discard(old)
        taken.add(new)


# Cada passo é SQL ou uma função (para transformar dados com código Python).
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
    # v2: currículo geral (versões aprovadas e última escrita do rascunho pela tool)
    """
    CREATE TABLE master_resumes (
        id INTEGER PRIMARY KEY,
        content_hash TEXT NOT NULL UNIQUE,
        content TEXT NOT NULL,
        approved_at TEXT NOT NULL
    );

    CREATE TABLE master_draft (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        file_hash TEXT NOT NULL,
        written_at TEXT NOT NULL
    );
    """,
    # v3: currículos personalizados gerados
    """
    CREATE TABLE resumes (
        id INTEGER PRIMARY KEY,
        master_resume_id INTEGER NOT NULL REFERENCES master_resumes (id),
        application_id INTEGER REFERENCES applications (id),
        label TEXT,
        lang TEXT NOT NULL DEFAULT 'en',
        selection TEXT NOT NULL,
        resolved TEXT NOT NULL,
        pdf_path TEXT NOT NULL,
        pages INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX resumes_application_id ON resumes (application_id);
    """,
    # v4: texto extraído do PDF do currículo, referência para revisar o rascunho
    """
    CREATE TABLE resume_sources (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL,
        pages TEXT NOT NULL,
        extracted_at TEXT NOT NULL
    );
    """,
    # v5: recalcula company_norm com a normalização completa (acentos, pontuação, sufixos)
    _renormalize_companies,
    # v6: cache de estimativas salariais
    """
    CREATE TABLE salary_searches (
        id INTEGER PRIMARY KEY,
        company TEXT,
        company_norm TEXT,
        role_key TEXT NOT NULL,
        seniority TEXT NOT NULL,
        currency TEXT NOT NULL,
        searched_at TEXT NOT NULL,
        note TEXT
    );
    CREATE INDEX salary_searches_key ON salary_searches (role_key, seniority, currency, company_norm);

    CREATE TABLE salary_points (
        id INTEGER PRIMARY KEY,
        search_id INTEGER NOT NULL REFERENCES salary_searches (id),
        source TEXT NOT NULL,
        source_url TEXT,
        contract TEXT NOT NULL,
        period TEXT NOT NULL,
        min_value REAL,
        avg_value REAL,
        max_value REAL,
        application_id INTEGER REFERENCES applications (id)
    );
    CREATE INDEX salary_points_search_id ON salary_points (search_id);
    """,
    # v7: última avaliação salarial usada na candidatura (JSON)
    "ALTER TABLE applications ADD COLUMN salary_evaluation TEXT",
    # v8: histórico de buscas de vagas
    """
    CREATE TABLE job_searches (
        id INTEGER PRIMARY KEY,
        query TEXT NOT NULL,
        query_norm TEXT NOT NULL,
        source TEXT NOT NULL,
        location TEXT,
        location_norm TEXT,
        filters TEXT,
        results_count INTEGER NOT NULL,
        searched_at TEXT NOT NULL,
        note TEXT
    );
    CREATE INDEX job_searches_key ON job_searches (query_norm, source, location_norm);
    """,
    # v9: origem (busca) e aderência ao currículo das vagas encontradas
    """
    ALTER TABLE applications ADD COLUMN search_id INTEGER REFERENCES job_searches (id);
    ALTER TABLE applications ADD COLUMN match_score INTEGER;
    ALTER TABLE applications ADD COLUMN match_terms TEXT;
    """,
    # v10: fontes do currículo de vários tipos (PDF, LinkedIn); content guarda páginas ou seções (JSON)
    """
    ALTER TABLE resume_sources RENAME COLUMN pages TO content;
    ALTER TABLE resume_sources ADD COLUMN kind TEXT NOT NULL DEFAULT 'pdf';
    """,
    # v11: url_canonical com as regras por plataforma (LinkedIn, Gupy, Indeed, Glassdoor)
    _recanonicalize_urls,
    # v12: execuções da busca em lote (search_run), com progresso e resumo (JSON)
    """
    CREATE TABLE search_runs (
        id INTEGER PRIMARY KEY,
        params TEXT NOT NULL,
        status TEXT NOT NULL,
        pid INTEGER,
        progress TEXT,
        summary TEXT,
        error TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT
    );
    """,
    # v13: regime da vaga (clt/pj/desconhecido); vagas antigas herdam o da faixa publicada, quando houve
    """
    ALTER TABLE applications ADD COLUMN contract TEXT NOT NULL DEFAULT 'desconhecido';
    UPDATE applications SET contract = COALESCE((
        SELECT p.contract FROM salary_points p
        WHERE p.application_id = applications.id AND p.source = 'vaga' AND p.contract IN ('clt', 'pj')
        ORDER BY p.id DESC LIMIT 1), 'desconhecido');
    """,
    # v14: pretensão em colunas (de onde veio a referência, valor de mercado, regra e pretensão
    # calculada; salary_expectation segue sendo a pretensão informada no formulário) e pesquisas
    # salariais descartadas (fonte ruim), que deixam de contar
    """
    ALTER TABLE applications ADD COLUMN salary_basis TEXT;
    ALTER TABLE applications ADD COLUMN salary_market REAL;
    ALTER TABLE applications ADD COLUMN salary_rule TEXT;
    ALTER TABLE applications ADD COLUMN salary_ask REAL;
    UPDATE applications SET
        salary_basis = json_extract(salary_evaluation, '$.basis'),
        salary_market = json_extract(salary_evaluation, '$.median'),
        salary_ask = json_extract(salary_evaluation, '$.value_to_inform'),
        salary_rule = CASE
            WHEN json_extract(salary_evaluation, '$.value_to_inform') IS NULL THEN NULL
            WHEN json_extract(salary_evaluation, '$.basis') = 'sem_dados' THEN 'minimo'
            ELSE 'teto' END
    WHERE salary_evaluation IS NOT NULL;
    ALTER TABLE salary_searches ADD COLUMN discarded_at TEXT;
    ALTER TABLE salary_searches ADD COLUMN discard_reason TEXT;
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
    for target, step in enumerate(MIGRATIONS[version:], start=version + 1):
        if callable(step):
            with conn:
                step(conn)
                conn.execute(f"PRAGMA user_version = {target}")
        else:
            with conn:
                conn.executescript(f"BEGIN; {step}; PRAGMA user_version = {target}; COMMIT;")
        log.info("Banco migrado para a versão %d", target)


def _backup(conn: sqlite3.Connection, path: Path, version: int) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    target = path.with_name(f"{path.name}.bak-v{version}-{stamp}")
    with sqlite3.connect(target) as copy:
        conn.backup(copy)
    copy.close()
    log.info("Backup do banco antes de migrar: %s", target)
