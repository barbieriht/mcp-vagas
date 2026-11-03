import base64
import json

import pytest

from vagas.job_posting import JobPostingError, classify_role, extract_job, read_job_posting
from vagas.normalize import canonical_url

GUPY_URL = "https://acme.gupy.io/jobs/123456?jobBoardSource=gupy_portal"
GUPY_JOB = {
    "id": 123456, "name": "Cientista de Dados Pleno", "jobType": "vacancy_type_effective",
    "workplaceType": "hybrid", "addressCity": "São Paulo", "addressState": "São Paulo", "addressCountry": "Brasil",
    "handicapped": False, "publishedAt": "2026-10-20T12:00:00.000Z",
    "description": "<p>Somos a <b>Acme</b>.</p>", "responsibilities": "<ul><li>Modelos com Python</li></ul>",
    "prerequisites": "<p>SQL e Spark</p>", "careerPage": {"name": "Acme Tecnologia"},
}
JSONLD = {
    "@context": "https://schema.org", "@type": "JobPosting", "title": "Senior Machine Learning Engineer",
    "hiringOrganization": {"@type": "Organization", "name": "Beta Corp"},
    "jobLocation": {"@type": "Place", "address": {"addressLocality": "Campinas", "addressRegion": "SP",
                                                  "addressCountry": "BR"}},
    "jobLocationType": "TELECOMMUTE", "employmentType": "CONTRACTOR",
    "baseSalary": {"@type": "MonetaryAmount", "currency": "BRL",
                   "value": {"@type": "QuantitativeValue", "minValue": 15000, "maxValue": 20000, "unitText": "MONTH"}},
    "description": "&lt;p&gt;Build ML systems with PyTorch.&lt;/p&gt;", "datePosted": "2026-10-01",
}


def gupy_html(job=GUPY_JOB):
    data = {"props": {"pageProps": {"job": job}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json" nonce="x">{json.dumps(data)}</script></body></html>'


def jsonld_html(obj=JSONLD):
    return (f'<html><head><script type="application/ld+json">{json.dumps({"@type": "BreadcrumbList"})}</script>'
            f'<script type="application/ld+json">{json.dumps(obj)}</script></head><body></body></html>')


def test_gupy_job_is_extracted_and_normalized():
    job = extract_job(GUPY_URL, gupy_html())

    assert job == {
        "url": GUPY_URL, "url_canonical": "https://acme.gupy.io/jobs/123456", "source": "gupy",
        "title": "Cientista de Dados Pleno", "company": "Acme Tecnologia",
        "location": "São Paulo, São Paulo, Brasil", "work_mode": "hibrido", "contract": "clt",
        "role_key": "data_scientist", "seniority": "pleno", "role_certain": True,
        "closed": False, "salary": None, "pcd_flag": False, "published_at": "2026-10-20",
        "description": "Somos a Acme.\n\nModelos com Python\n\nSQL e Spark",
    }


@pytest.mark.parametrize("job_type, contract, seniority", [
    ("vacancy_type_legal_entity", "pj", "pleno"),
    ("vacancy_type_internship", "desconhecido", "estagio"),
    ("vacancy_type_talent_pool", "desconhecido", "pleno"),
])
def test_gupy_job_types(job_type, contract, seniority):
    job = extract_job(GUPY_URL, gupy_html({**GUPY_JOB, "jobType": job_type}))

    assert (job["contract"], job["seniority"]) == (contract, seniority)


def test_jsonld_job_is_extracted_with_salary():
    job = extract_job("https://careers.beta.com/jobs/42", jsonld_html())

    assert job["source"] == "outro"
    assert (job["title"], job["company"], job["location"]) == ("Senior Machine Learning Engineer", "Beta Corp", "Campinas, SP, BR")
    assert (job["work_mode"], job["contract"], job["role_key"], job["seniority"]) == ("remoto", "pj", "ml_engineer", "senior")
    assert job["salary"] == {"currency": "BRL", "period": "mes", "min_value": 15000, "max_value": 20000}
    assert job["description"] == "Build ML systems with PyTorch."
    assert job["published_at"] == "2026-10-01"


def test_linkedin_jsonld_marks_source():
    job = extract_job("https://br.linkedin.com/jobs/view/cientista-de-dados-at-x-4482018735", jsonld_html(
        {**JSONLD, "title": "Cientista de Dados", "jobLocationType": None, "baseSalary": None, "employmentType": "FULL_TIME"}))

    assert (job["source"], job["url_canonical"], job["work_mode"], job["contract"], job["salary"]) == (
        "linkedin", "https://linkedin.com/jobs/view/4482018735", None, "desconhecido", None)


def test_page_without_job_data_is_a_readable_error():
    with pytest.raises(JobPostingError, match="dados estruturados"):
        extract_job("https://example.com/vaga", "<html><body>Vaga legal</body></html>")


@pytest.mark.parametrize("title, role_key, seniority, certain", [
    ("Cientista de Dados Sênior", "data_scientist", "senior", True),
    ("Data Scientist II", "data_scientist", "pleno", True),
    ("Data Scientist", "data_scientist", None, True),
    ("CIENTISTA DADOS SR", "data_scientist", "senior", True),
    ("CIENTISTA DADOS ESPECIALISTA", "data_scientist", "especialista", True),
    ("ANALISTA DE ENGENHARIA DE MACHINE LEARNING SENIOR", "ml_engineer", "senior", True),
    ("ESPECIALISTA ENG. DE MACHINE LEARNING", "ml_engineer", "especialista", True),
    ("Desenvolvedor IA III", "ai_engineer", "senior", True),
    ("Desenvolvedor(a) de Inteligência Artificial Sênior Robótica e Navegação Autônoma", "ai_engineer", "senior",
     True),
    ("Engenheiro(a) de Visão Computacional Pleno(a)", "ml_engineer", "pleno", True),
    ("Computer Vision Engineer I", "ml_engineer", "junior", True),
    ("Data Science Specialist", "data_scientist", "especialista", True),
    ("Especialista Senior em Ciencia de Dados — Crédito", "data_scientist", "especialista", True),
    ("Engenheiro de Machine Learning I Sênior I Híbrido SP", "ml_engineer", "senior", True),
    ("Cientista de Dados Pl.", "data_scientist", "pleno", True),
    ("Cientista de Dados Sr.", "data_scientist", "senior", True),
    ("Pessoa Engenheira de Software Sênior | IA Generativa", "ai_engineer", "senior", True),
    ("Engenheiro(a) de Machine Learning Jr", "ml_engineer", "junior", True),
    ("AI Engineer - LLM", "ai_engineer", None, True),
    ("Engenheira de Dados Especialista", "data_engineer", "especialista", True),
    ("Analista de Dados Pl", "data_analyst", "pleno", True),
    ("Estágio em Ciência de Dados", "data_scientist", "estagio", True),
    ("Staff Machine Learning Engineer", "ml_engineer", "especialista", True),
    ("Desenvolvedor Backend", "outro", None, False),
])
def test_classify_role(title, role_key, seniority, certain):
    assert classify_role(title) == (role_key, seniority, certain)


def test_gupy_short_links_are_canonicalized_to_the_job_id():
    token = base64.b64encode(json.dumps({"jobId": 12603351, "source": "gupy_portal"}).encode()).decode()

    assert canonical_url(f"https://acme.gupy.io/job/{token}?jobBoardSource=gupy_portal") == \
        "https://acme.gupy.io/jobs/12603351"


class FakeFetcher:
    def __init__(self, status=200, body=""):
        self.status, self.body, self.calls = status, body, []

    def __call__(self, url):
        self.calls.append(url)
        return self.status, self.body


def test_read_job_posting_fetches_and_extracts():
    fetcher = FakeFetcher(body=gupy_html())

    assert read_job_posting(GUPY_URL, fetcher=fetcher)["title"] == "Cientista de Dados Pleno"
    assert fetcher.calls == [GUPY_URL]


@pytest.mark.parametrize("status, body, message", [
    (403, "Blocked - Indeed.com", "bloqueou"),
    (401, "", "bloqueou"),
    (200, "<title>Just a moment...</title>", "bloqueou"),
    (404, "not found", "404"),
])
def test_blocked_or_missing_pages_are_readable_errors(status, body, message):
    with pytest.raises(JobPostingError, match=message):
        read_job_posting("https://br.indeed.com/viewjob?jk=abc", fetcher=FakeFetcher(status, body))
