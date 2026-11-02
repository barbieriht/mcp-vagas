from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from vagas.db import connect
from vagas.job_board import JobBoard, linkedin_search_url, parse_linkedin_search
from vagas.job_posting import JobPostingError, read_job_posting
from vagas.job_search import JobSearchStore
from vagas.repo import Repo, VagasError

CRITERIA = "- Cargos alvo: data_scientist\n- Locais aceitos para híbrido e presencial: São Paulo\n"


def card(job_id, title="Cientista de Dados", company="Acme", location="São Paulo, São Paulo, Brazil",
         date="2026-10-30", salary=None):
    pay = f'<span class="job-search-card__salary-info"> {salary} </span>' if salary else ""
    return f"""<li>
<div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:{job_id}">
<a class="base-card__full-link" href="https://br.linkedin.com/jobs/view/x-at-acme-{job_id}?position=1&amp;refId=a">
<span class="sr-only"> {title} </span></a>
<div class="base-search-card__info"><h3 class="base-search-card__title"> {title} </h3>
<h4 class="base-search-card__subtitle"><a class="hidden-nested-link" href="#"> {company} </a></h4>
<div class="base-search-card__metadata"><span class="job-search-card__location"> {location} </span>{pay}
<time class="job-search-card__listdate" datetime="{date}"> 2 days ago </time></div></div></div></li>"""


class Fetcher:
    """Responde por "start" (10 cartões por página) e guarda os parâmetros pedidos."""

    def __init__(self, pages=None, status=200):
        self.pages, self.status, self.calls = pages or {}, status, []

    def __call__(self, url):
        params = parse_qs(urlsplit(url).query)
        self.calls.append(params)
        return self.status, self.pages.get(int(params.get("start", ["0"])[0]), "")


def test_cards_are_parsed():
    jobs = parse_linkedin_search(card(1, salary="R$ 8.000,00/mês - R$ 10.000,00/mês") + card(2, company="Beta"))

    assert jobs[0] == {"title": "Cientista de Dados", "company": "Acme", "url": "https://linkedin.com/jobs/view/1",
                       "published_at": "2026-10-30", "location": "São Paulo, São Paulo, Brazil", "work_mode": None,
                       "contract": "desconhecido", "pcd_flag": None,
                       "salary": {"currency": "BRL", "period": "mes", "min_value": 8000.0, "max_value": 10000.0}}
    assert jobs[1]["company"] == "Beta" and jobs[1]["salary"] is None


def test_search_url_maps_filters():
    url = linkedin_search_url("cientista de dados", None, {"work_modes": ["remoto", "hibrido"], "posted": "week"},
                              page=3)
    params = parse_qs(urlsplit(url).query)

    assert url.startswith("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?")
    assert params == {"keywords": ["cientista de dados"], "location": ["Brazil"], "f_WT": ["2,3"],
                      "f_TPR": ["r604800"], "start": ["20"]}
    assert "location=S%C3%A3o+Paulo" in linkedin_search_url("x", "São Paulo", {}, page=1)


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


def board(conn, fetcher, tmp_path):
    criteria = tmp_path / "c.md"
    criteria.write_text(CRITERIA, encoding="utf-8")
    return JobBoard(conn, fetcher=fetcher, criteria_path=criteria, draft_path=tmp_path / "c.yaml")


def test_linkedin_search_pages_until_a_short_page(conn, tmp_path):
    fetcher = Fetcher({0: "".join(card(i) for i in range(10)), 10: "".join(card(i) for i in range(10, 14))})
    Repo(conn).add_application(company="Acme", role="DS", source="linkedin",
                               url="https://www.linkedin.com/jobs/view/12/", status="a_aplicar")

    result = board(conn, fetcher, tmp_path).search_jobs("cientista de dados", "linkedin",
                                                         filters={"max_pages": 5})

    assert (result["pages_read"], len(result["results"]), result["total"]) == (2, 14, 14)
    assert result["results"][12]["registered"] == {"id": 1, "status": "a_aplicar"}
    saved = JobSearchStore(conn).find_job_search("cientista de dados", "linkedin")["search"]
    assert saved["results_count"] == 14


def test_empty_linkedin_page_ends_the_search(conn, tmp_path):
    result = board(conn, Fetcher({}), tmp_path).search_jobs("nada", "linkedin")

    assert (result["pages_read"], result["results"], result["total"]) == (1, [], 0)


@pytest.mark.parametrize("status, message", [(429, "limitou"), (999, "limitou"), (403, "bloqueou")])
def test_linkedin_limits_stop_the_search(conn, tmp_path, status, message):
    with pytest.raises(VagasError, match=message):
        board(conn, Fetcher(status=status), tmp_path).search_jobs("x", "linkedin")
    assert JobSearchStore(conn).find_job_search("x", "linkedin")["search"] is None


@pytest.mark.parametrize("source, filters, message", [
    ("linkedin", {"state": "São Paulo"}, "state"),
    ("gupy", {"posted": "week"}, "posted"),
    ("linkedin", {"posted": "ontem"}, "posted"),
    ("indeed", None, "navegador"),
    ("glassdoor", None, "navegador"),
])
def test_filters_per_source(conn, tmp_path, source, filters, message):
    with pytest.raises(VagasError, match=message):
        board(conn, Fetcher(), tmp_path).search_jobs("x", source, filters=filters)


def test_suggestions_cover_gupy_and_linkedin(conn, tmp_path):
    searches = board(conn, Fetcher(), tmp_path).suggest_job_searches()["searches"]

    linkedin = [s for s in searches if s["source"] == "linkedin"]
    assert {s["source"] for s in searches} == {"gupy", "linkedin"}
    assert ("cientista de dados", None) in {(s["query"], s["location"]) for s in linkedin}
    assert all(s["filters"]["max_pages"] == 1 and s["filters"]["posted"] == "week" for s in linkedin)
    assert len(linkedin) < len([s for s in searches if s["source"] == "gupy"]) + 1


class PageFetcher:
    def __init__(self, status, body):
        self.status, self.body = status, body

    def __call__(self, url):
        return self.status, self.body


@pytest.mark.parametrize("url, status, body", [
    ("https://br.indeed.com/viewjob?jk=abc", 403, "<title>Blocked - Indeed.com</title>"),
    ("https://www.glassdoor.com.br/job-listing/x-JV_KO0,5.htm?jl=1", 403, ""),
    ("https://www.glassdoor.com.br/job-listing/x-JV_KO0,5.htm?jl=1", 200, "<title>Just a moment...</title>"),
])
def test_indeed_and_glassdoor_blocks_are_clear_errors(url, status, body):
    with pytest.raises(JobPostingError, match="bloqueou.*navegador"):
        read_job_posting(url, fetcher=PageFetcher(status, body))
