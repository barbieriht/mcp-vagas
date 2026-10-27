import pytest

from vagas.repo import VagasError

LINKEDIN = "https://www.linkedin.com/jobs/view/4012345678/"


def add(repo, **overrides):
    fields = dict(company="Nubank", role="Data Scientist", url=LINKEDIN, source="linkedin")
    fields.update(overrides)
    return repo.add_application(**fields)


def test_add_creates_application_with_status_aplicada(repo):
    result = add(repo, work_mode="remoto", seniority="pleno", location="Brasil",
                 salary_expectation="R$ 10.000", description="Requisitos: Python")

    assert result["created"] is True
    app = result["application"]
    assert app["id"] > 0
    assert app["status"] == "aplicada"
    assert app["company"] == "Nubank"
    assert app["work_mode"] == "remoto"
    assert app["description"] == "Requisitos: Python"
    assert app["created_at"] == app["updated_at"]


def test_add_records_creation_event(repo):
    app = add(repo)["application"]

    events = repo.events(app["id"])

    assert [(e["from_status"], e["to_status"]) for e in events] == [(None, "aplicada")]


def test_duplicate_url_returns_existing_without_error(repo):
    first = add(repo)["application"]

    second = add(repo, role="Outro cargo", url=LINKEDIN + "?utm_source=share&utm_medium=x#top")

    assert second["created"] is False
    assert second["application"] == first
    assert len(repo.events(first["id"])) == 1


def test_find_by_url_ignores_tracking_and_fragment(repo):
    app = add(repo, url="https://empresa.com/vagas/123?utm_campaign=x&ref=abc#descricao")["application"]

    matches = repo.find_application(url="HTTP://EMPRESA.com/vagas/123/?ref=abc")

    assert matches == [app]


def test_find_keeps_meaningful_query_params(repo):
    add(repo, url="https://empresa.com/vaga?id=1")

    assert repo.find_application(url="https://empresa.com/vaga?id=2") == []


def test_find_unknown_url_returns_empty(repo):
    add(repo)

    assert repo.find_application(url="https://outra.com/vaga/1") == []


def test_find_without_criteria_is_an_error(repo):
    with pytest.raises(VagasError, match="url"):
        repo.find_application()


def test_application_without_url_is_allowed_and_never_deduplicated(repo):
    a = add(repo, url=None)
    b = add(repo, url=None)

    assert a["created"] and b["created"]
    assert a["application"]["id"] != b["application"]["id"]


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"source": "monster"}, "source"),
        ({"work_mode": "home office"}, "work_mode"),
        ({"company": "  "}, "company"),
        ({"role": ""}, "role"),
    ],
)
def test_invalid_input_is_rejected_with_readable_message(repo, overrides, message):
    with pytest.raises(VagasError, match=message):
        add(repo, **overrides)
