from datetime import datetime, timedelta, timezone

import pytest

from vagas.db import connect
from vagas.job_search import JobSearchStore
from vagas.repo import VagasError

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.at = T0

    def __call__(self):
        return self.at.isoformat(timespec="seconds")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(db_path, clock, monkeypatch):
    monkeypatch.delenv("VAGAS_JOB_SEARCH_MIN_HOURS", raising=False)
    conn = connect(db_path)
    yield JobSearchStore(conn, now=clock)
    conn.close()


def save(store, **overrides):
    fields = dict(query="Data Scientist Python", source="linkedin", location="Remoto",
                  filters={"posted": "24h", "remote": True}, results_count=37)
    fields.update(overrides)
    return store.save_job_search(**fields)


def test_saves_and_finds_search(store):
    saved = save(store, note="muitas vagas de estágio")

    found = store.find_job_search(query="Data Scientist Python", source="linkedin", location="Remoto")

    assert found["recent"] is True
    assert found["hours_since"] == 0
    assert found["min_hours"] == 24
    search = found["search"]
    assert search["id"] == saved["search_id"]
    assert (search["query"], search["source"], search["location"]) == ("Data Scientist Python", "linkedin", "Remoto")
    assert search["filters"] == {"posted": "24h", "remote": True}
    assert (search["results_count"], search["note"]) == (37, "muitas vagas de estágio")
    assert search["searched_at"] == T0.isoformat(timespec="seconds")


def test_never_searched(store):
    assert store.find_job_search(query="ML Engineer", source="gupy") == {
        "search": None, "recent": False, "hours_since": None, "min_hours": 24,
    }


@pytest.mark.parametrize("query, location", [
    ("data scientist python", "remoto"),
    ("  DATA   Scientist  Python ", "REMOTO"),
    ("Data Scientist Pythón", "Rémoto"),
])
def test_query_and_location_are_compared_normalized(store, query, location):
    save(store)

    assert store.find_job_search(query=query, source="linkedin", location=location)["search"] is not None


@pytest.mark.parametrize("other", [
    {"source": "gupy"}, {"location": "São Paulo"}, {"location": None}, {"query": "Data Scientist"},
])
def test_different_searches_do_not_match(store, other):
    save(store)
    criteria = {"query": "Data Scientist Python", "source": "linkedin", "location": "Remoto", **other}

    assert store.find_job_search(**criteria)["search"] is None


def test_search_without_location_matches_only_without_location(store):
    save(store, location=None)

    assert store.find_job_search(query="Data Scientist Python", source="linkedin")["search"] is not None
    assert store.find_job_search(query="Data Scientist Python", source="linkedin", location="")["search"] is not None
    assert store.find_job_search(query="Data Scientist Python", source="linkedin", location="Remoto")["search"] is None


def test_recent_until_interval_then_can_search_again(store, clock):
    save(store)

    clock.at = T0 + timedelta(hours=23, minutes=59, seconds=59)
    assert store.find_job_search(query="Data Scientist Python", source="linkedin", location="Remoto")["recent"] is True

    clock.at = T0 + timedelta(hours=24)
    found = store.find_job_search(query="Data Scientist Python", source="linkedin", location="Remoto")
    assert (found["recent"], found["hours_since"]) == (False, 24)


def test_interval_is_configurable(db_path, clock, monkeypatch):
    monkeypatch.setenv("VAGAS_JOB_SEARCH_MIN_HOURS", "6")
    conn = connect(db_path)
    store = JobSearchStore(conn, now=clock)
    save(store)

    clock.at = T0 + timedelta(hours=7)

    found = store.find_job_search(query="Data Scientist Python", source="linkedin", location="Remoto")
    assert (found["recent"], found["min_hours"]) == (False, 6)


def test_latest_equivalent_search_is_returned(store, clock):
    save(store, results_count=10)
    clock.at = T0 + timedelta(days=2)
    latest = save(store, results_count=0)

    found = store.find_job_search(query="Data Scientist Python", source="linkedin", location="Remoto")

    assert (found["search"]["id"], found["search"]["results_count"], found["recent"]) == (latest["search_id"], 0, True)


def test_search_without_results_is_recorded(store):
    saved = save(store, results_count=0, filters=None, note="nenhuma vaga")

    assert saved["search_id"] > 0


@pytest.mark.parametrize("bad, field", [
    ({"source": "catho"}, "source"),
    ({"results_count": -1}, "results_count"),
    ({"query": "   "}, "query"),
])
def test_invalid_input_is_rejected(store, bad, field):
    with pytest.raises(VagasError, match=field):
        save(store, **bad)


def test_find_rejects_invalid_input(store):
    with pytest.raises(VagasError, match="source"):
        store.find_job_search(query="x", source="catho")
    with pytest.raises(VagasError, match="query"):
        store.find_job_search(query="", source="linkedin")
