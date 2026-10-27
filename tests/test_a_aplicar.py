import pytest

from vagas.db import connect
from vagas.job_search import JobSearchStore
from vagas.repo import Repo, VagasError

TERMS = {"matched": ["Python", "SQL"], "missing": ["Spark"]}


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return Repo(conn)


@pytest.fixture
def search_id(conn):
    return JobSearchStore(conn).save_job_search(query="Data Scientist", source="linkedin", results_count=5)["search_id"]


def found(repo, origin, **overrides):
    fields = dict(company="Nubank", role="Data Scientist", source="linkedin", url="https://x.com/1",
                  status="a_aplicar", search_id=origin, match_score=67, match_terms=TERMS,
                  description="Python, SQL e Spark")
    fields.update(overrides)
    return repo.add_application(**fields)


def test_found_job_enters_the_work_list(repo, search_id):
    app = found(repo, search_id)["application"]

    assert app["status"] == "a_aplicar"
    assert (app["search_id"], app["match_score"], app["match_terms"]) == (search_id, 67, TERMS)
    assert [(e["from_status"], e["to_status"]) for e in repo.events(app["id"])] == [(None, "a_aplicar")]


def test_origin_and_match_are_optional(repo):
    app = repo.add_application(company="Itaú", role="DS", source="gupy", status="a_aplicar")["application"]

    assert (app["search_id"], app["match_score"], app["match_terms"]) == (None, None, None)


def test_match_is_kept_when_applying(repo, search_id):
    app = found(repo, search_id)["application"]

    applied = repo.update_application(app["id"], status="aplicada", note="Candidatura enviada")

    assert (applied["status"], applied["match_score"], applied["search_id"]) == ("aplicada", 67, search_id)
    assert [e["to_status"] for e in repo.get_history(app["id"])["events"]] == ["a_aplicar", "aplicada"]


@pytest.mark.parametrize("target, extra", [
    ("pendente_usuario", {"pending": "CPF"}),
    ("descartada", {"discard_reason": "Vaga encerrada"}),
])
def test_other_transitions_from_work_list(repo, search_id, target, extra):
    app = found(repo, search_id)["application"]

    assert repo.update_application(app["id"], status=target, **extra)["status"] == target


def test_found_job_is_deduplicated_like_any_other(repo, search_id):
    first = found(repo, search_id)["application"]

    again = found(repo, search_id, match_score=90)

    assert again["created"] is False
    assert again["application"]["match_score"] == first["match_score"] == 67


@pytest.mark.parametrize("bad, field", [
    ({"search_id": 999}, "Busca 999"),
    ({"match_score": 101}, "match_score"),
    ({"match_score": -1}, "match_score"),
    ({"match_terms": {"matched": ["Python"]}}, "match_terms"),
    ({"match_terms": {"matched": "Python", "missing": []}}, "match_terms"),
    ({"match_terms": {"matched": [], "missing": [], "extra": []}}, "match_terms"),
])
def test_invalid_origin_or_match_is_rejected(repo, search_id, bad, field):
    with pytest.raises(VagasError, match=field):
        found(repo, search_id, **bad)


def test_found_by_company_shows_work_list_entry(repo, search_id):
    app = found(repo, search_id)["application"]

    assert repo.find_application(company="nubank s.a.") == [app]
