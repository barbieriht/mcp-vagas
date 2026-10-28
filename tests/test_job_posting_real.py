"""Leitura real de vagas (opt-in): VAGAS_TEST_JOB_URLS com URLs separadas por vírgula (Gupy, LinkedIn...)."""

import os

import pytest

from vagas.job_posting import read_job_posting

URLS = [u for u in os.environ.get("VAGAS_TEST_JOB_URLS", "").split(",") if u.strip()]


@pytest.mark.skipif(not URLS, reason="defina VAGAS_TEST_JOB_URLS para ler vagas reais")
@pytest.mark.parametrize("url", URLS)
def test_real_job_posting(url):
    job = read_job_posting(url)

    assert job["title"] and job["company"] and len(job["description"]) > 100
    assert job["url_canonical"]
