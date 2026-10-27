import itertools
import sqlite3

import pytest

from vagas.db import MIGRATIONS, _renormalize_companies, connect
from vagas.repo import Repo, VagasError


@pytest.fixture
def repo(db_path):
    ticks = itertools.count()
    conn = connect(db_path)
    yield Repo(conn, now=lambda: f"2026-10-27T12:00:{next(ticks):02d}+00:00")
    conn.close()


def add(repo, company, role="Data Scientist", url=None, **extra):
    return repo.add_application(company=company, role=role, source="linkedin", url=url, **extra)["application"]


@pytest.mark.parametrize("stored, searched", [
    ("nubank", "Nubank S.A."),
    ("NUBANK Ltda", "nubank"),
    ("Nubank S/A", "Nubank"),
    ("Itaú Unibanco S.A.", "itau unibanco"),
    ("Acme Inc.", "ACME"),
    ("Empresa X Eireli", "empresa x"),
    ("  Mercado   Livre  ", "Mercado Livre"),
])
def test_company_variants_match(repo, stored, searched):
    app = add(repo, stored)

    assert repo.find_application(company=searched) == [app]


def test_all_jobs_of_the_company_newest_first(repo):
    older = add(repo, "Nubank", role="Data Analyst", url="https://x.com/1")
    newer = add(repo, "Nubank S.A.", role="ML Engineer", url="https://x.com/2")
    add(repo, "Itaú", url="https://x.com/3")

    assert repo.find_application(company="nubank") == [newer, older]


def test_prefix_does_not_collide(repo):
    add(repo, "Nubank")

    assert repo.find_application(company="Nu") == []
    assert repo.find_application(company="Nubank Seguros") == []


def test_suffix_alone_is_not_stripped_to_nothing(repo):
    app = add(repo, "S.A.")

    assert repo.find_application(company="sa") == [app]


def test_discarded_job_is_found_by_company_with_reason(repo):
    app = add(repo, "CI&T", status="descartada", discard_reason="Empresa ignorada")

    [found] = repo.find_application(company="ci&t")
    assert found == app and found["discard_reason"] == "Empresa ignorada"


def test_url_and_company_together_are_combined_without_duplicates(repo):
    a = add(repo, "Nubank", url="https://x.com/1")
    b = add(repo, "Nubank", url="https://x.com/2")
    c = add(repo, "Itaú", url="https://x.com/3")

    assert repo.find_application(url="https://x.com/3", company="nubank") == [c, b, a]


def test_blank_company_counts_as_missing(repo):
    with pytest.raises(VagasError, match="company"):
        repo.find_application(company="   ")


def test_existing_rows_are_renormalized_by_migration(tmp_path):
    path = tmp_path / "old.db"
    before = MIGRATIONS.index(_renormalize_companies)
    old = sqlite3.connect(path)
    for step in MIGRATIONS[:before]:
        old.executescript(step)
    old.execute(
        "INSERT INTO applications (company, company_norm, role, source, status, created_at, updated_at) "
        "VALUES ('Nubank S.A.', 'nubank s.a.', 'DS', 'linkedin', 'aplicada', 'x', 'x')"
    )
    old.execute(f"PRAGMA user_version = {before}")
    old.commit()
    old.close()

    conn = connect(path)

    assert conn.execute("SELECT company_norm FROM applications").fetchone()[0] == "nubank"
    assert list(tmp_path.glob("old.db.bak-*"))
