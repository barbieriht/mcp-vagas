from datetime import datetime, timedelta, timezone

import pytest

from vagas.db import connect
from vagas.repo import Repo, VagasError

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.at = T0

    def __call__(self):
        return self.at.isoformat(timespec="seconds")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def repo(db_path, clock):
    conn = connect(db_path)
    yield Repo(conn, now=clock)
    conn.close()


def add(repo, clock, day, company, **extra):
    clock.at = T0 + timedelta(days=day)
    fields = dict(company=company, role="DS", source="linkedin", url=f"https://x.com/{company}")
    fields.update(extra)
    return repo.add_application(**fields)["application"]


@pytest.fixture
def apps(repo, clock):
    return {
        "nubank": add(repo, clock, 0, "Nubank"),
        "itau": add(repo, clock, 1, "Itau", source="gupy", status="pendente_usuario", pending="CPF"),
        "ciandt": add(repo, clock, 2, "CI&T", status="descartada", discard_reason="Empresa ignorada"),
        "ifood": add(repo, clock, 3, "iFood", status="a_aplicar"),
        "stone": add(repo, clock, 40, "Stone", source="gupy"),
    }


def ids(result, apps):
    by_id = {app["id"]: name for name, app in apps.items()}
    return [by_id[app["id"]] for app in result["applications"]]


def test_without_filters_lists_everything_newest_first(repo, apps):
    result = repo.list_applications()

    assert ids(result, apps) == ["stone", "ifood", "ciandt", "itau", "nubank"]
    assert result["count"] == 5


def test_filter_by_status(repo, apps):
    assert ids(repo.list_applications(status="aplicada"), apps) == ["stone", "nubank"]


def test_invalid_status_is_rejected(repo, apps):
    with pytest.raises(VagasError, match="status"):
        repo.list_applications(status="entrevista")


def test_only_pending(repo, apps, clock):
    repo.update_application(apps["nubank"]["id"], pending="Teste técnico até sexta")

    assert ids(repo.list_applications(only_pending=True), apps) == ["itau", "nubank"]


def test_filter_by_source(repo, apps):
    assert ids(repo.list_applications(source="gupy"), apps) == ["stone", "itau"]


def test_filter_by_creation_date(repo, apps):
    assert ids(repo.list_applications(since="2026-10-04"), apps) == ["stone", "ifood"]
    assert ids(repo.list_applications(since="2026-10-03T12:00:00+00:00"), apps) == ["stone", "ifood", "ciandt"]
    assert ids(repo.list_applications(since="2026-10-03T12:00:01+00:00"), apps) == ["stone", "ifood"]


def test_invalid_date_is_rejected(repo, apps):
    with pytest.raises(VagasError, match="since"):
        repo.list_applications(since="ontem")


def test_stale_applied_applications(repo, apps, clock):
    clock.at = T0 + timedelta(days=45)

    result = repo.list_applications(stale_days=30)

    assert ids(result, apps) == ["nubank"]
    assert result["applications"][0]["last_event_at"] == T0.isoformat(timespec="seconds")


def test_recent_event_makes_application_not_stale(repo, apps, clock):
    clock.at = T0 + timedelta(days=35)
    repo.update_application(apps["nubank"]["id"], note="Recrutadora respondeu")
    clock.at = T0 + timedelta(days=45)

    assert ids(repo.list_applications(stale_days=30), apps) == []


def test_stale_boundary(repo, apps, clock):
    clock.at = T0 + timedelta(days=30)
    assert ids(repo.list_applications(stale_days=30), apps) == []

    clock.at = T0 + timedelta(days=30, seconds=1)
    assert ids(repo.list_applications(stale_days=30), apps) == ["nubank"]


def test_negative_stale_days_is_rejected(repo, apps):
    with pytest.raises(VagasError, match="stale_days"):
        repo.list_applications(stale_days=-1)


def test_filters_combine(repo, apps, clock):
    clock.at = T0 + timedelta(days=45)

    assert ids(repo.list_applications(source="gupy", status="aplicada"), apps) == ["stone"]
    assert ids(repo.list_applications(source="linkedin", stale_days=30), apps) == ["nubank"]
    assert ids(repo.list_applications(source="gupy", since="2026-10-02", status="aplicada"), apps) == ["stone"]


def test_every_item_has_last_event_at(repo, apps):
    assert all(app["last_event_at"] for app in repo.list_applications()["applications"])
