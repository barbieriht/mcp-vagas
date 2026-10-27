from datetime import datetime, timedelta, timezone

import pytest

from vagas.db import connect
from vagas.repo import Repo

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo(db_path):
    clock = {"at": T0}
    conn = connect(db_path)
    r = Repo(conn, now=lambda: clock["at"].isoformat(timespec="seconds"))
    r.clock = clock
    yield r
    conn.close()


def found(repo, day, company, score, source="linkedin", status="a_aplicar"):
    repo.clock["at"] = T0 + timedelta(days=day)
    terms = None if score is None else {"matched": ["Python"], "missing": ["Spark"]}
    return repo.add_application(company=company, role="DS", source=source, url=f"https://x.com/{company}",
                                status=status, match_score=score, match_terms=terms)["application"]


def companies(result):
    return [app["company"] for app in result["applications"]]


def test_work_list_is_ordered_by_match_then_newest(repo):
    found(repo, 0, "Low", 40)
    found(repo, 1, "NoScore", None)
    found(repo, 2, "HighOld", 90)
    found(repo, 3, "Mid", 70)
    found(repo, 4, "HighNew", 90)

    result = repo.list_applications(status="a_aplicar")

    assert companies(result) == ["HighNew", "HighOld", "Mid", "Low", "NoScore"]
    assert result["applications"][0]["match_terms"] == {"matched": ["Python"], "missing": ["Spark"]}
    assert result["applications"][0]["match_score"] == 90


def test_other_filters_still_apply_to_work_list(repo):
    found(repo, 0, "Linkedin", 90)
    found(repo, 1, "Gupy", 50, source="gupy")
    found(repo, 2, "GupyHigh", 80, source="gupy")

    assert companies(repo.list_applications(status="a_aplicar", source="gupy")) == ["GupyHigh", "Gupy"]
    assert companies(repo.list_applications(status="a_aplicar", since="2026-10-02")) == ["GupyHigh", "Gupy"]


def test_other_statuses_keep_newest_first(repo):
    found(repo, 0, "Old", 99, status="aplicada")
    found(repo, 1, "New", 10, status="aplicada")

    assert companies(repo.list_applications(status="aplicada")) == ["New", "Old"]
    assert companies(repo.list_applications()) == ["New", "Old"]
