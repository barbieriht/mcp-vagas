"""Busca real na Gupy (opt-in): VAGAS_TEST_GUPY_SEARCH=1. Faz uma requisição ao portal público."""

import os

import pytest

from vagas.db import connect
from vagas.job_board import JobBoard


@pytest.mark.skipif(os.environ.get("VAGAS_TEST_GUPY_SEARCH") != "1", reason="defina VAGAS_TEST_GUPY_SEARCH=1")
def test_real_gupy_search(tmp_path):
    criteria = tmp_path / "c.md"
    criteria.write_text("- Cargos alvo: data_scientist\n", encoding="utf-8")
    conn = connect(tmp_path / "vagas.db")
    result = JobBoard(conn, criteria_path=criteria, draft_path=tmp_path / "c.yaml").search_jobs(
        "cientista de dados", "gupy", filters={"work_modes": ["remoto"], "max_pages": 1})
    conn.close()

    assert result["total"] > 0 and result["results"]
    job = result["results"][0]
    assert job["url"].startswith("https://") and "/jobs/" in job["url"] and job["title"] and job["company"]
    assert {j["work_mode"] for j in result["results"]} == {"remoto"}


@pytest.mark.skipif(os.environ.get("VAGAS_TEST_LINKEDIN_SEARCH") != "1", reason="defina VAGAS_TEST_LINKEDIN_SEARCH=1")
def test_real_linkedin_search(tmp_path):
    criteria = tmp_path / "c.md"
    criteria.write_text("- Cargos alvo: data_scientist\n", encoding="utf-8")
    conn = connect(tmp_path / "vagas.db")
    result = JobBoard(conn, criteria_path=criteria, draft_path=tmp_path / "c.yaml").search_jobs(
        "cientista de dados", "linkedin", location="São Paulo", filters={"posted": "week", "max_pages": 1})
    conn.close()

    assert result["results"]
    job = result["results"][0]
    assert job["url"].startswith("https://linkedin.com/jobs/view/") and job["title"] and job["company"]
