import json

import pytest

from vagas import job_posting
from vagas.job_posting import JobPostingError, extract_job, infer_work_mode, read_job_posting

URL = "https://br.linkedin.com/jobs/view/cientista-de-dados-at-acme-4480000001?trk=public_jobs"


def linkedin_html(title="Cientista de Dados", company="ACME", location="São Paulo, São Paulo, Brazil",
                  criteria=(("Seniority level", "Mid-Senior level"), ("Employment type", "Full-time")),
                  description="<p>Modelos com Python.</p>", salary=None, jsonld=None, similar_salary=True):
    items = "".join(f'<li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">'
                    f' {k} </h3><span class="description__job-criteria-text description__job-criteria-text--criteria">'
                    f' {v} </span></li>' for k, v in criteria)
    pay = f'<div class="salary compensation__salary"> {salary} </div>' if salary else ""
    ld = f'<script type="application/ld+json">{json.dumps(jsonld)}</script>' if jsonld else ""
    similar = ('<section class="similar-jobs"><span class="main-job-card__salary-info"> R$ 181.705,00 - '
               'R$ 217.944,00 </span><span>Totalmente remoto</span></section>') if similar_salary else ""
    return f"""<html><head><title>{title} at {company} | LinkedIn Jobs</title>{ld}</head><body>
<h1 class="top-card-layout__title topcard__title">{title}</h1>
<span class="topcard__flavor"><a class="topcard__org-name-link topcard__flavor--black-link" href="#"> {company} </a></span>
<span class="topcard__flavor topcard__flavor--bullet"> {location} </span>
{pay}
<div class="show-more-less-html__markup show-more-less-html__markup--clamp-after-5"> {description} </div>
<ul class="description__job-criteria-list">{items}</ul>
{similar}
</body></html>"""


def test_linkedin_page_without_jsonld_is_read_from_html():
    job = extract_job(URL, linkedin_html(description="<p>Modelos com Python.</p><p>Modelo de trabalho híbrido.</p>"))

    assert (job["source"], job["url_canonical"]) == ("linkedin", "https://linkedin.com/jobs/view/4480000001")
    assert (job["title"], job["company"], job["location"]) == ("Cientista de Dados", "ACME",
                                                              "São Paulo, São Paulo, Brazil")
    assert (job["role_key"], job["seniority"], job["contract"]) == ("data_scientist", None, "desconhecido")
    assert (job["work_mode"], job["work_mode_inferred"]) == ("hibrido", True)
    assert "Modelos com Python" in job["description"]
    assert job["salary"] is None  # a faixa das vagas semelhantes não é da vaga


@pytest.mark.parametrize("criteria, title, seniority, contract", [
    ((("Nível de experiência", "Estágio"), ("Tipo de emprego", "Estágio")), "Cientista de Dados", "estagio",
     "desconhecido"),
    ((("Seniority level", "Entry level"), ("Employment type", "Contract")), "Data Scientist", "junior", "pj"),
    ((("Nível de experiência", "Assistente"), ("Tipo de emprego", "Contrato")), "Data Scientist", "junior", "pj"),
    ((("Seniority level", "Entry level"),), "Senior Data Scientist", "senior", "desconhecido"),  # título manda
    ((("Seniority level", "Mid-Senior level"),), "Data Scientist", None, "desconhecido"),
])
def test_linkedin_criteria_fill_seniority_and_contract(criteria, title, seniority, contract):
    job = extract_job(URL, linkedin_html(title=title, criteria=criteria))

    assert (job["seniority"], job["contract"]) == (seniority, contract)


@pytest.mark.parametrize("text, mode", [
    ("Vaga 100% remota para todo o Brasil.", "remoto"),
    ("Trabalho remoto, home office.", "remoto"),
    ("Modelo híbrido: 3 dias presenciais por semana.", "hibrido"),
    ("Hybrid work in São Paulo.", "hibrido"),
    ("Atuação presencial em Barueri.", "presencial"),
    ("On-site role.", "presencial"),
    ("Início remoto, depois presencial.", None),
    ("Sem informação.", None),
])
def test_work_mode_inference(text, mode):
    assert infer_work_mode(text) == mode


def test_linkedin_published_salary_with_period():
    job = extract_job(URL, linkedin_html(salary="R$ 8.000,00/mês - R$ 12.000,00/mês"))

    assert job["salary"] == {"currency": "BRL", "period": "mes", "min_value": 8000.0, "max_value": 12000.0}


@pytest.mark.parametrize("text, expected", [
    ("$120,000.00/yr - $150,000.00/yr", {"currency": "USD", "period": "ano", "min_value": 120000.0,
                                         "max_value": 150000.0}),
    ("R$ 50,00/hora", {"currency": "BRL", "period": "hora", "min_value": 50.0, "max_value": 50.0}),
    ("R$ 181.705,00 - R$ 217.944,00", {"currency": "BRL", "period": None, "min_value": 181705.0,
                                       "max_value": 217944.0}),
])
def test_linkedin_salary_formats(text, expected):
    assert extract_job(URL, linkedin_html(salary=text))["salary"] == expected


def test_jsonld_on_linkedin_page_is_merged():
    jsonld = {"@type": "JobPosting", "title": "Cientista de Dados", "hiringOrganization": {"name": "ACME"},
              "jobLocationType": "TELECOMMUTE", "datePosted": "2026-10-21T02:07:32.000Z",
              "employmentType": "CONTRACTOR", "description": "Modelos com Python."}

    job = extract_job(URL, linkedin_html(jsonld=jsonld))

    assert (job["work_mode"], job["work_mode_inferred"], job["contract"], job["published_at"]) == (
        "remoto", False, "pj", "2026-10-21")


class FakeFetcher:
    def __init__(self, status=200, body=""):
        self.status, self.body, self.calls = status, body, []

    def __call__(self, url):
        self.calls.append(url)
        return self.status, self.body


def test_linkedin_is_fetched_by_the_canonical_job_url():
    fetcher = FakeFetcher(body=linkedin_html())

    job = read_job_posting("https://www.linkedin.com/jobs/search/?currentJobId=4480000001&keywords=x", fetcher)

    assert fetcher.calls == ["https://www.linkedin.com/jobs/view/4480000001/"]
    assert job["title"] == "Cientista de Dados"


@pytest.mark.parametrize("status, body, message", [
    (429, "", "limitou"),
    (999, "", "limitou"),
    (200, '<html><head><title>Sign Up | LinkedIn</title></head><body>authwall</body></html>', "login"),
])
def test_linkedin_limits_and_login_are_readable_errors(status, body, message):
    with pytest.raises(JobPostingError, match=message):
        read_job_posting(URL, fetcher=FakeFetcher(status, body))


def test_linkedin_has_its_own_longer_interval(monkeypatch):
    monkeypatch.delenv("VAGAS_SITE_MIN_SECONDS", raising=False)
    monkeypatch.delenv("VAGAS_LINKEDIN_JOBS_MIN_SECONDS", raising=False)

    assert job_posting.min_interval("www.linkedin.com") == 20
    assert job_posting.min_interval("br.linkedin.com") == 20
    assert job_posting.min_interval("acme.gupy.io") == 3
    monkeypatch.setenv("VAGAS_LINKEDIN_JOBS_MIN_SECONDS", "45")
    assert job_posting.min_interval("www.linkedin.com") == 45
    assert job_posting.site_key("br.linkedin.com") == job_posting.site_key("www.linkedin.com")
