import sqlite3

from vagas.db import LATEST_VERSION, connect, default_db_path


def columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def backups(db_path):
    return sorted(p.name for p in db_path.parent.glob(f"{db_path.name}.bak-*"))


V14_COLUMNS = {"applications": ("salary_basis", "salary_market", "salary_rule", "salary_ask"),
               "salary_searches": ("discarded_at", "discard_reason")}


def drop_v14(conn):
    for table, names in V14_COLUMNS.items():
        for name in names:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {name}")


def test_new_database_gets_latest_schema(db_path):
    conn = connect(db_path)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
    assert columns(conn, "applications") == {
        "id", "company", "company_norm", "role", "url", "url_canonical", "source",
        "seniority", "work_mode", "location", "salary_expectation", "description",
        "status", "pending", "discard_reason", "created_at", "updated_at", "salary_evaluation",
        "search_id", "match_score", "match_terms", "contract",
        "salary_basis", "salary_market", "salary_rule", "salary_ask",
    }
    assert columns(conn, "events") == {
        "id", "application_id", "at", "from_status", "to_status", "note",
    }


def test_connection_uses_wal_and_busy_timeout(db_path):
    conn = connect(db_path)

    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000


def test_new_database_is_not_backed_up(db_path):
    connect(db_path).close()

    assert backups(db_path) == []


def test_reopening_current_database_is_not_backed_up(db_path):
    connect(db_path).close()
    connect(db_path).close()

    assert backups(db_path) == []


def test_existing_database_with_older_version_is_backed_up_before_migrating(db_path):
    old = sqlite3.connect(db_path)
    old.execute("CREATE TABLE legado (x TEXT)")
    old.execute("INSERT INTO legado VALUES ('preservar')")
    old.commit()
    old.close()

    connect(db_path).close()

    [backup] = backups(db_path)
    copy = sqlite3.connect(db_path.parent / backup)
    assert copy.execute("PRAGMA user_version").fetchone()[0] == 0
    assert copy.execute("SELECT x FROM legado").fetchall() == [("preservar",)]


def test_db_path_comes_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VAGAS_DB", str(tmp_path / "outro.db"))

    assert default_db_path() == tmp_path / "outro.db"


def test_db_path_defaults_to_local_share(monkeypatch, tmp_path):
    monkeypatch.delenv("VAGAS_DB", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert default_db_path() == tmp_path / ".local/share/vagas/vagas.db"


def test_contract_is_backfilled_from_published_salary_points(db_path):
    conn = connect(db_path)
    now = "2026-01-01T00:00:00+00:00"
    for i, contract in enumerate(["pj", "clt", "desconhecido"], start=1):
        conn.execute("INSERT INTO applications (id, company, company_norm, role, source, status, created_at, "
                     "updated_at) VALUES (?, 'A', 'a', 'DS', 'gupy', 'a_aplicar', ?, ?)", (i, now, now))
        conn.execute("INSERT INTO salary_searches (id, role_key, seniority, currency, searched_at) "
                     "VALUES (?, 'data_scientist', 'pleno', 'BRL', ?)", (i, now))
        conn.execute("INSERT INTO salary_points (search_id, source, contract, period, application_id) "
                     "VALUES (?, 'vaga', ?, 'mes', ?)", (i, contract, i))
    conn.execute("INSERT INTO applications (id, company, company_norm, role, source, status, created_at, "
                 "updated_at) VALUES (4, 'B', 'b', 'DS', 'gupy', 'a_aplicar', ?, ?)", (now, now))
    conn.commit()
    conn.execute("ALTER TABLE applications DROP COLUMN contract")
    drop_v14(conn)
    conn.execute("PRAGMA user_version = 12")
    conn.commit()
    conn.close()

    conn = connect(db_path)

    rows = conn.execute("SELECT id, contract FROM applications ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(1, "pj"), (2, "clt"), (3, "desconhecido"), (4, "desconhecido")]


def test_salary_columns_are_backfilled_from_the_evaluation(db_path):
    import json

    conn = connect(db_path)
    now = "2026-11-01T00:00:00+00:00"
    evaluations = {
        1: {"decision": "aplicar", "basis": "mercado", "median": 20500.0, "value_to_inform": 20500},
        2: {"decision": "aplicar", "basis": "sem_dados", "median": None, "value_to_inform": 10500},
        3: {"decision": "pesquisar", "basis": None, "median": None, "value_to_inform": None},
    }
    for i, evaluation in evaluations.items():
        conn.execute("INSERT INTO applications (id, company, company_norm, role, source, status, created_at, "
                     "updated_at, salary_evaluation) VALUES (?, 'A', 'a', 'DS', 'gupy', 'a_aplicar', ?, ?, ?)",
                     (i, now, now, json.dumps(evaluation)))
    conn.commit()
    drop_v14(conn)
    conn.execute(f"PRAGMA user_version = {LATEST_VERSION - 1}")
    conn.commit()
    conn.close()

    conn = connect(db_path)

    rows = conn.execute("SELECT id, salary_basis, salary_market, salary_rule, salary_ask FROM applications "
                        "ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(1, "mercado", 20500.0, "teto", 20500.0),
                                        (2, "sem_dados", None, "minimo", 10500.0),
                                        (3, None, None, None, None)]
