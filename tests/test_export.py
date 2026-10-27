import csv
from datetime import datetime, timezone

import pytest

from vagas.db import connect
from vagas.export import export_csv
from vagas.repo import Repo

NOW = datetime(2026, 10, 27, 15, 4, 5, tzinfo=timezone.utc)


@pytest.fixture
def repo(db_path):
    conn = connect(db_path)
    yield Repo(conn, now=lambda: NOW.isoformat(timespec="seconds"))
    conn.close()


def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def test_exports_header_and_one_row_per_application(repo, tmp_path):
    repo.add_application(company="Nubank", role="DS", source="linkedin", url="https://x.com/1")
    repo.add_application(company="Itaú", role="ML", source="gupy", status="pendente_usuario", pending="CPF")

    result = export_csv(repo, tmp_path / "exports")

    rows = read(result["path"])
    assert result["rows"] == 2 == len(rows)
    assert {"id", "company", "role", "status", "url", "url_canonical", "pending", "created_at",
            "last_event_at", "match_score", "salary_evaluation"} <= set(rows[0])
    assert {row["company"] for row in rows} == {"Nubank", "Itaú"}


def test_text_with_accents_separators_quotes_and_newlines_survives(repo, tmp_path):
    description = 'Requisitos: Python; SQL, "Spark"\nDiferencial: São Paulo – híbrido'
    repo.add_application(company="Ação & Cia; Ltda", role="Cientista de Dados", source="outro",
                         description=description, status="a_aplicar",
                         match_score=80, match_terms={"matched": ["Python"], "missing": ["Spark"]})

    [row] = read(export_csv(repo, tmp_path / "exports")["path"])

    assert row["description"] == description
    assert row["company"] == "Ação & Cia; Ltda"
    assert row["match_terms"] == '{"matched": ["Python"], "missing": ["Spark"]}'
    assert row["match_score"] == "80"
    assert row["salary_evaluation"] == ""


def test_successive_exports_do_not_overwrite(repo, tmp_path):
    out = tmp_path / "exports"
    first = export_csv(repo, out)["path"]
    second = export_csv(repo, out)["path"]

    assert first.endswith("vagas_20261027-150405.csv")
    assert second.endswith("vagas_20261027-150405_2.csv")


def test_empty_database_exports_only_the_header(repo, tmp_path):
    result = export_csv(repo, tmp_path / "exports")

    with open(result["path"], encoding="utf-8-sig") as f:
        assert f.read().startswith("id;company;")
    assert result["rows"] == 0
