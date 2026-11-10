"""Vagas no painel (sem HTTP): lista com filtros, contagens por status e detalhe de cada vaga."""

import pytest

from vagas.jobs_view import job_detail, list_jobs
from vagas.repo import VagasError


@pytest.fixture
def jobs(repo):
    rows = [
        ("Acme", "Data Scientist", "gupy", "a_aplicar", 80, "São Paulo"),
        ("Beta", "ML Engineer", "linkedin", "a_aplicar", 95, "Remoto"),
        ("Gama", "Data Analyst", "linkedin", "a_aplicar", None, "Campinas"),
        ("Delta", "Data Scientist Sênior", "linkedin", "aplicada", 70, "São Paulo"),
        ("Épsilon", "AI Engineer", "gupy", "descartada", 40, "Rio de Janeiro"),
    ]
    ids = {}
    for number, (company, role, source, status, score, location) in enumerate(rows, start=1):
        extra = {"discard_reason": "fora do perfil"} if status == "descartada" else {}
        app = repo.add_application(company=company, role=role, source=source, status=status, location=location,
                                   url=f"https://example.com/vagas/{number}", **extra)["application"]
        if score is not None:
            repo.set_match(app["id"], score, {"matched": ["Python"], "missing": ["Spark"]})
        ids[company] = app["id"]
    repo.update_application(ids["Delta"], pending="Fazer o teste técnico")
    return ids


def roles(result):
    return [item["role"] for item in result["items"]]


def test_counts_by_status_cover_the_whole_base(repo, jobs):
    result = list_jobs(repo.conn, {})

    assert result["total"] == 5
    assert result["counts"]["a_aplicar"] == 3 and result["counts"]["aplicada"] == 1
    assert result["counts"]["descartada"] == 1
    assert {"value": "a_aplicar", "label": "A aplicar"} in result["statuses"]


def test_work_list_is_ordered_by_match_with_unscored_last(repo, jobs):
    result = list_jobs(repo.conn, {"status": "a_aplicar"})

    assert roles(result) == ["ML Engineer", "Data Scientist", "Data Analyst"]


def test_filters_combine(repo, jobs):
    assert roles(list_jobs(repo.conn, {"source": "linkedin", "min_score": "75"})) == ["ML Engineer"]
    assert roles(list_jobs(repo.conn, {"text": "data scientist"})) == ["Data Scientist Sênior", "Data Scientist"]
    assert roles(list_jobs(repo.conn, {"text": "epsilon"})) == ["AI Engineer"]  # sem acento também acha
    assert roles(list_jobs(repo.conn, {"only_pending": "1"})) == ["Data Scientist Sênior"]


def test_pagination(repo, jobs):
    first = list_jobs(repo.conn, {"per_page": "2", "page": "1"})
    last = list_jobs(repo.conn, {"per_page": "2", "page": "3"})

    assert len(first["items"]) == 2 and first["pages"] == 3 and len(last["items"]) == 1


@pytest.mark.parametrize("bad, message", [
    ({"status": "contratado"}, "status"), ({"source": "orkut"}, "site"), ({"since": "ontem"}, "data"),
    ({"min_score": "muito"}, "aderência"), ({"page": "zero"}, "página"),
])
def test_invalid_filters_explain_what_to_fix(repo, jobs, bad, message):
    with pytest.raises(VagasError, match=message):
        list_jobs(repo.conn, bad)


def test_list_items_are_light_and_links_are_only_http(repo, jobs):
    item = list_jobs(repo.conn, {"text": "Acme"})["items"][0]

    assert "description" not in item and item["url"].startswith("https://")
    assert item["status_label"] == "A aplicar"


def test_detail_has_history_resumes_and_description(repo, jobs):
    detail = job_detail(repo.conn, jobs["Delta"])

    assert detail["application"]["role"] == "Data Scientist Sênior"
    assert [e["to_status"] for e in detail["events"]][0] == "aplicada"
    assert detail["application"]["pending"] == "Fazer o teste técnico"
    assert detail["resumes"] == []


def test_unknown_job_is_a_readable_error(repo):
    with pytest.raises(VagasError, match="999"):
        job_detail(repo.conn, 999)


@pytest.mark.parametrize("url, expected", [
    ("https://acme.gupy.io/jobs/1", "https://acme.gupy.io/jobs/1"), ("javascript:alert(1)", None),
    ("data:text/html,x", None), (None, None),
])
def test_only_http_links_become_links(url, expected):
    from vagas.jobs_view import _safe_url

    assert _safe_url(url) == expected
