import sqlite3

import pytest

from vagas.db import MIGRATIONS, _recanonicalize_urls, connect
from vagas.normalize import canonical_url
from vagas.repo import Repo

SAME_JOB = [
    # LinkedIn: visualização direta, com slug, busca, coleções, subdomínio de país e rastreamento
    ("https://www.linkedin.com/jobs/view/4012345678/",
     "https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=data%20scientist&origin=JOBS_HOME"),
    ("https://www.linkedin.com/jobs/view/4012345678/",
     "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4012345678"),
    ("https://www.linkedin.com/jobs/view/4012345678/",
     "https://br.linkedin.com/jobs/view/cientista-de-dados-at-nubank-4012345678?refId=abc&trackingId=xyz%3D%3D&trk=public_jobs"),
    ("https://www.linkedin.com/jobs/view/4012345678/",
     "linkedin.com/jobs/view/4012345678#top"),
    # Gupy: parâmetros de origem e barra final
    ("https://nubank.gupy.io/jobs/8123456",
     "https://nubank.gupy.io/jobs/8123456/?jobBoardSource=gupy_public_page&utm_source=linkedin"),
    ("https://nubank.gupy.io/jobs/8123456", "http://NUBANK.gupy.io/jobs/8123456#descricao"),
    # Indeed: viewjob com jk, busca com vjk, subdomínio de país
    ("https://br.indeed.com/viewjob?jk=7f3a9c2b1d4e5f60",
     "https://br.indeed.com/viewjob?jk=7f3a9c2b1d4e5f60&from=serp&vjs=3&tk=1hx"),
    ("https://br.indeed.com/viewjob?jk=7f3a9c2b1d4e5f60",
     "https://br.indeed.com/jobs?q=cientista+de+dados&l=S%C3%A3o+Paulo&vjk=7f3a9c2b1d4e5f60"),
    ("https://br.indeed.com/viewjob?jk=7f3a9c2b1d4e5f60", "https://www.indeed.com/viewjob?jk=7f3a9c2b1d4e5f60"),
    # Glassdoor: jl na página da vaga, jobListingId em links de parceiros, domínio de país
    ("https://www.glassdoor.com.br/job-listing/data-scientist-nubank-JV_IC2479949_KO0,14_KE15,21.htm?jl=1009123456789",
     "https://www.glassdoor.com.br/job-listing/cientista-de-dados-JV_KO0,18.htm?jl=1009123456789&src=GD_JOB_AD&t=SR"),
    ("https://www.glassdoor.com.br/job-listing/x.htm?jl=1009123456789",
     "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=1009123456789&pos=101"),
    # Outros sites: limpeza geral
    ("https://empresa.com/carreiras/vaga-123?utm_campaign=x&trk=feed#descricao",
     "HTTP://www.EMPRESA.com/carreiras/vaga-123/"),
]

DIFFERENT_JOBS = [
    ("https://www.linkedin.com/jobs/view/4012345678/", "https://www.linkedin.com/jobs/view/4012345679/"),
    ("https://nubank.gupy.io/jobs/8123456", "https://nubank.gupy.io/jobs/8123457"),
    ("https://nubank.gupy.io/jobs/8123456", "https://itau.gupy.io/jobs/8123456"),
    ("https://br.indeed.com/viewjob?jk=aaa111", "https://br.indeed.com/viewjob?jk=bbb222"),
    ("https://www.glassdoor.com.br/job-listing/x.htm?jl=1", "https://www.glassdoor.com.br/job-listing/x.htm?jl=2"),
    ("https://empresa.com/vaga?id=1", "https://empresa.com/vaga?id=2"),
    ("https://empresa.com/vagas/1", "https://outra.com/vagas/1"),
]


@pytest.fixture
def repo(db_path):
    conn = connect(db_path)
    yield Repo(conn)
    conn.close()


@pytest.mark.parametrize("first, second", SAME_JOB)
def test_same_job_is_deduplicated_across_url_variants(repo, first, second):
    created = repo.add_application(company="Nubank", role="DS", source="outro", url=first)["application"]

    assert repo.find_application(url=second) == [created]
    duplicate = repo.add_application(company="Nubank", role="DS", source="outro", url=second)
    assert duplicate["created"] is False


@pytest.mark.parametrize("first, second", DIFFERENT_JOBS)
def test_different_jobs_do_not_collide(repo, first, second):
    repo.add_application(company="X", role="DS", source="outro", url=first)

    assert repo.add_application(company="X", role="DS", source="outro", url=second)["created"] is True


def test_record_keeps_original_and_canonical_url(repo):
    original = "https://www.linkedin.com/jobs/search/?currentJobId=4012345678&keywords=x"

    app = repo.add_application(company="Nubank", role="DS", source="linkedin", url=original)["application"]

    assert app["url"] == original
    assert app["url_canonical"] == "https://linkedin.com/jobs/view/4012345678"


@pytest.mark.parametrize("url, canonical", [
    ("https://nubank.gupy.io/jobs/8123456?jobBoardSource=x", "https://nubank.gupy.io/jobs/8123456"),
    ("https://br.indeed.com/jobs?q=x&vjk=abc", "https://indeed.com/viewjob?jk=abc"),
    ("https://www.glassdoor.com.br/job-listing/x.htm?jl=99", "https://glassdoor.com/job-listing?jl=99"),
])
def test_canonical_forms(url, canonical):
    assert canonical_url(url) == canonical


def test_platform_pages_without_job_id_fall_back_to_general_cleaning():
    assert canonical_url("https://www.linkedin.com/jobs/search/?keywords=data") == \
        "https://linkedin.com/jobs/search?keywords=data"


def test_migration_recanonicalizes_existing_urls_without_breaking_on_collisions(tmp_path):
    path = tmp_path / "old.db"
    before = MIGRATIONS.index(_recanonicalize_urls)
    old = sqlite3.connect(path)
    for step in MIGRATIONS[:before]:
        if callable(step):
            step(old)
        else:
            old.executescript(step)
    rows = [
        ("A", "https://www.linkedin.com/jobs/view/4012345678/", "https://www.linkedin.com/jobs/view/4012345678"),
        ("B", "https://www.linkedin.com/jobs/search/?currentJobId=4012345678",
         "https://www.linkedin.com/jobs/search?currentJobId=4012345678"),
        ("C", "https://nubank.gupy.io/jobs/1?jobBoardSource=x", "https://nubank.gupy.io/jobs/1?jobBoardSource=x"),
    ]
    old.executemany(
        "INSERT INTO applications (company, company_norm, role, url, url_canonical, source, status, created_at, "
        "updated_at) VALUES (?, ?, 'DS', ?, ?, 'linkedin', 'aplicada', 't', 't')",
        [(c, c.lower(), url, canonical) for c, url, canonical in rows],
    )
    old.execute(f"PRAGMA user_version = {before}")
    old.commit()
    old.close()

    conn = connect(path)
    canonical = dict(conn.execute("SELECT company, url_canonical FROM applications").fetchall())

    assert canonical["A"] == "https://linkedin.com/jobs/view/4012345678"
    assert canonical["B"] == "https://www.linkedin.com/jobs/search?currentJobId=4012345678"
    assert canonical["C"] == "https://nubank.gupy.io/jobs/1"
