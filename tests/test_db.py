import sqlite3

from vagas.db import LATEST_VERSION, connect, default_db_path


def columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def backups(db_path):
    return sorted(p.name for p in db_path.parent.glob(f"{db_path.name}.bak-*"))


def test_new_database_gets_full_v1_schema(db_path):
    conn = connect(db_path)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION == 1
    assert columns(conn, "applications") == {
        "id", "company", "company_norm", "role", "url", "url_canonical", "source",
        "seniority", "work_mode", "location", "salary_expectation", "description",
        "status", "pending", "discard_reason", "created_at", "updated_at",
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
