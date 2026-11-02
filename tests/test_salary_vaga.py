from datetime import datetime, timedelta, timezone

import pytest

from vagas.db import connect
from vagas.repo import Repo, VagasError
from vagas.salary import SalaryStore

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
KEY = {"role_key": "data_scientist", "seniority": "pleno", "currency": "BRL"}
POLICY = {"my_min": 10000, "my_max": 14000, "pj_multiplier": 1.4}


class Clock:
    def __init__(self):
        self.at = T0

    def __call__(self):
        return self.at.isoformat(timespec="seconds")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def store(conn, clock, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    return SalaryStore(conn, now=clock)


@pytest.fixture
def app(conn):
    return Repo(conn).add_application(company="Nubank", role="DS", source="linkedin",
                                      status="aplicada")["application"]


def published(store, app_id, lo=None, hi=None, avg=None, contract="clt", period="mes"):
    return store.save_salary_estimate(**KEY, company="Nubank", application_id=app_id, points=[
        {"source": "vaga", "period": period, "contract": contract,
         "min_value": lo, "max_value": hi, "avg_value": avg},
    ])


def evaluate(store, app_id, contract="clt", **overrides):
    return store.evaluate_salary(**KEY, contract=contract, company="Nubank", application_id=app_id,
                                 **{**POLICY, **overrides})


def test_published_range_takes_priority(store, app):
    store.save_salary_estimate(**KEY, company="Nubank", points=[
        {"source": "glassdoor", "period": "mes", "contract": "clt", "avg_value": 9000}])
    published(store, app["id"], lo=11000, hi=15000)

    result = evaluate(store, app["id"])

    assert (result["basis"], result["decision"]) == ("vaga", "aplicar")
    assert result["range"] == [11000, 15000]
    assert result["value_to_inform"] == 13000
    assert result["needs_research"] is False


def test_published_ceiling_below_my_minimum_rejects(store, app):
    published(store, app["id"], lo=6000, hi=9000)

    result = evaluate(store, app["id"])

    assert result["decision"] == "nao_aplicar"
    assert "9.000" in result["reason"] and "10.000" in result["reason"]


@pytest.mark.parametrize("lo, hi, value", [
    (8000, 11000, 10000),
    (12000, 20000, 14000),
    (10000, 10500, 10200),
])
def test_value_is_midpoint_within_my_minimum_and_job_ceiling(store, app, lo, hi, value):
    published(store, app["id"], lo=lo, hi=hi)

    assert evaluate(store, app["id"])["value_to_inform"] == value


def test_value_never_exceeds_job_ceiling_without_my_max(store, app):
    published(store, app["id"], lo=12000, hi=20000)

    assert evaluate(store, app["id"], my_max=None)["value_to_inform"] == 16000


def test_single_published_value(store, app):
    published(store, app["id"], avg=12000)

    result = evaluate(store, app["id"])

    assert (result["range"], result["value_to_inform"]) == ([12000, 12000], 12000)


def test_published_range_in_pj_job(store, app):
    published(store, app["id"], lo=14000, hi=18000, contract="pj")

    result = evaluate(store, app["id"], contract="pj")

    assert (result["decision"], result["value_to_inform"], result["contract"]) == ("aplicar", 16000, "pj")


def test_published_annual_range_is_converted(store, app):
    published(store, app["id"], lo=133300, hi=186620, period="ano")

    assert evaluate(store, app["id"])["range"] == [10000, 14000]


def test_published_range_does_not_expire(store, app, clock):
    published(store, app["id"], lo=11000, hi=15000)
    clock.at = T0 + timedelta(days=400)

    assert evaluate(store, app["id"])["basis"] == "vaga"


def test_published_range_is_only_for_its_application(store, app, conn):
    other = Repo(conn).add_application(company="Nubank", role="ML", source="gupy")["application"]
    published(store, app["id"], lo=11000, hi=15000)

    result = evaluate(store, other["id"])

    assert result["basis"] == "empresa"


def test_points_for_an_application_must_come_from_the_job(store, app):
    with pytest.raises(VagasError, match="vaga"):
        store.save_salary_estimate(**KEY, company="Nubank", application_id=app["id"], points=[
            {"source": "glassdoor", "period": "mes", "avg_value": 1}])


@pytest.mark.parametrize("call", ["save", "evaluate"])
def test_unknown_application_is_rejected(store, call):
    with pytest.raises(VagasError, match="Candidatura 999"):
        if call == "save":
            published(store, 999, lo=1, hi=2)
        else:
            evaluate(store, 999)


def test_evaluation_is_recorded_on_the_application(store, app, conn):
    published(store, app["id"], lo=11000, hi=15000)

    result = evaluate(store, app["id"])

    history = Repo(conn).get_history(app["id"])
    saved = history["application"]["salary_evaluation"]
    assert saved["decision"] == result["decision"] == "aplicar"
    assert saved["value_to_inform"] == 13000
    assert saved["evaluated_at"] == T0.isoformat(timespec="seconds")
    assert saved["policy"] == {"band": None, "mode": "minimo", "my_min": 10000, "my_max": 14000,
                               "pj_multiplier": 1.4}


def test_latest_evaluation_replaces_previous(store, app, conn):
    first = evaluate(store, app["id"])
    published(store, app["id"], lo=11000, hi=15000)
    second = evaluate(store, app["id"])

    saved = Repo(conn).get(app["id"])["salary_evaluation"]
    assert (first["decision"], second["decision"], saved["decision"]) == ("pesquisar", "aplicar", "aplicar")


def test_without_application_nothing_is_recorded(store, app, conn):
    store.save_salary_estimate(**KEY, points=[{"source": "x", "period": "mes", "avg_value": 12000}])

    store.evaluate_salary(**KEY, contract="clt", **POLICY)

    assert Repo(conn).get(app["id"])["salary_evaluation"] is None
