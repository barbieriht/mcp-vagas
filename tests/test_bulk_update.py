"""bulk_update_applications: simulação com token, uma transação, um evento por linha e status protegidos."""

from datetime import datetime, timedelta, timezone

import pytest
from mcp import Client

from vagas.db import connect
from vagas.repo import Repo, VagasError

pytestmark = pytest.mark.anyio

DISCARD = {"status": "descartada", "discard_reason": "Estágio fora das senioridades buscadas."}


class Clock:
    def __init__(self):
        self.at = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.at += timedelta(seconds=1)
        return self.at.isoformat(timespec="seconds")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def repo(db_path, clock):
    conn = connect(db_path)
    yield Repo(conn, now=clock)
    conn.close()


def add(repo, role="Data Scientist Intern", status="a_aplicar", seniority="estagio", **extra):
    if status == "pendente_usuario":
        extra.setdefault("pending", "CPF")
    return repo.add_application(company="Acme", role=role, source="gupy", status=status, seniority=seniority,
                                **extra)["application"]


def interns():
    return {"status": "a_aplicar", "seniority": ["estagio"]}


def test_dry_run_is_the_default_and_writes_nothing(repo):
    a, b = add(repo), add(repo)
    add(repo, seniority="pleno")

    plan = repo.bulk_update(filter=interns(), **DISCARD)

    assert plan["would_affect"] == 2 and plan["skipped"] == []
    assert [row["id"] for row in plan["sample"]] == [a["id"], b["id"]]
    assert plan["confirm_token"] and plan["expires_at"]
    assert {repo.get(i)["status"] for i in (a["id"], b["id"])} == {"a_aplicar"}
    assert len(repo.events(a["id"])) == 1


def test_apply_with_the_token_updates_every_row_and_writes_one_event_each(repo):
    a, b = add(repo), add(repo)
    plan = repo.bulk_update(filter=interns(), **DISCARD)

    done = repo.bulk_update(filter=interns(), **DISCARD, dry_run=False, confirm_token=plan["confirm_token"])

    assert done == {"updated": 2, "skipped": [], "ids": [a["id"], b["id"]]}
    for app_id in (a["id"], b["id"]):
        app = repo.get(app_id)
        assert app["status"] == "descartada" and app["discard_reason"] == DISCARD["discard_reason"]
        assert [(e["from_status"], e["to_status"]) for e in repo.events(app_id)] == [
            (None, "a_aplicar"), ("a_aplicar", "descartada")]


def test_note_and_pending_without_status_change(repo):
    a = add(repo)
    plan = repo.bulk_update(ids=[a["id"]], note="revisado em lote", pending="confirmar modalidade")

    repo.bulk_update(ids=[a["id"]], note="revisado em lote", pending="confirmar modalidade", dry_run=False,
                     confirm_token=plan["confirm_token"])

    assert repo.get(a["id"])["pending"] == "confirmar modalidade"
    assert repo.events(a["id"])[-1]["note"] == "revisado em lote"


def test_apply_without_a_token_is_refused(repo):
    add(repo)

    with pytest.raises(VagasError, match="confirm_token"):
        repo.bulk_update(filter=interns(), **DISCARD, dry_run=False)


def test_token_is_bound_to_the_change(repo):
    add(repo)
    plan = repo.bulk_update(filter=interns(), **DISCARD)

    with pytest.raises(VagasError, match="simulação"):
        repo.bulk_update(filter=interns(), status="descartada", discard_reason="outro motivo", dry_run=False,
                         confirm_token=plan["confirm_token"])


def test_token_expires_after_ten_minutes(repo, clock):
    a = add(repo)
    plan = repo.bulk_update(filter=interns(), **DISCARD)
    clock.at += timedelta(minutes=11)

    with pytest.raises(VagasError, match="expirou"):
        repo.bulk_update(filter=interns(), **DISCARD, dry_run=False, confirm_token=plan["confirm_token"])
    assert repo.get(a["id"])["status"] == "a_aplicar"


def test_a_forged_token_is_refused(repo):
    add(repo)
    plan = repo.bulk_update(filter=interns(), **DISCARD)
    issued, _, digest = plan["confirm_token"].rpartition(".")

    with pytest.raises(VagasError, match="simulação"):
        repo.bulk_update(filter=interns(), **DISCARD, dry_run=False, confirm_token=f"{issued}.{'0' * len(digest)}")


def test_matched_set_changing_between_dry_run_and_apply_is_refused(repo):
    a = add(repo)
    plan = repo.bulk_update(filter=interns(), **DISCARD)
    newcomer = add(repo)

    with pytest.raises(VagasError, match="mudou.*simulação"):
        repo.bulk_update(filter=interns(), **DISCARD, dry_run=False, confirm_token=plan["confirm_token"])
    assert {repo.get(i)["status"] for i in (a["id"], newcomer["id"])} == {"a_aplicar"}


def test_one_row_failing_validation_rolls_back_the_whole_change(repo):
    first, second = add(repo, pending="CPF"), add(repo, pending="RG")
    change = {"status": "pendente_usuario", "note": "aguardando documentos"}
    plan = repo.bulk_update(ids=[first["id"], second["id"]], **change)
    repo.update_application(second["id"], pending="")  # sem pendência, pendente_usuario não vale para ela

    with pytest.raises(VagasError, match=rf"{second['id']}.*pendente_usuario.*Nada foi gravado"):
        repo.bulk_update(ids=[first["id"], second["id"]], **change, dry_run=False, confirm_token=plan["confirm_token"])

    assert repo.get(first["id"])["status"] == "a_aplicar"
    assert len(repo.events(first["id"])) == 1


def test_dry_run_reports_the_same_validation_error_as_the_apply(repo):
    a = add(repo)

    with pytest.raises(VagasError, match=rf"{a['id']}.*pendente_usuario"):
        repo.bulk_update(ids=[a["id"]], status="pendente_usuario")


def test_same_status_rows_are_skipped(repo):
    a = add(repo)
    done_already = add(repo, status="descartada", discard_reason="x")

    plan = repo.bulk_update(ids=[a["id"], done_already["id"]], **DISCARD)

    assert plan["would_affect"] == 1
    assert plan["skipped"] == [{"id": done_already["id"], "reason": "já está com status 'descartada'"}]


def test_discard_requires_a_reason(repo):
    add(repo)

    with pytest.raises(VagasError, match="discard_reason"):
        repo.bulk_update(filter=interns(), status="descartada")


def test_protected_statuses_are_untouched_unless_the_filter_names_them(repo):
    open_ = add(repo)
    applied = add(repo, status="aplicada")

    plan = repo.bulk_update(filter={"seniority": ["estagio"]}, **DISCARD)

    assert plan["would_affect"] == 1 and [r["id"] for r in plan["sample"]] == [open_["id"]]
    assert plan["skipped"] == [{"id": applied["id"], "reason": "status 'aplicada' protegido: inclua-o em "
                                                                "filter.status para alterá-lo"}]
    named = repo.bulk_update(filter={"seniority": ["estagio"], "status": ["a_aplicar", "aplicada"]}, **DISCARD)
    assert named["would_affect"] == 2


def test_explicit_ids_still_protect_applied_rows(repo):
    applied = add(repo, status="aplicada")

    plan = repo.bulk_update(ids=[applied["id"]], status="recusada")

    assert plan["would_affect"] == 0 and plan["skipped"][0]["id"] == applied["id"]
    assert "confirm_token" not in plan


def test_max_affected_caps_the_change(repo):
    for _ in range(3):
        add(repo)

    with pytest.raises(VagasError, match=r"3 candidaturas.*max_affected.*2"):
        repo.bulk_update(filter=interns(), **DISCARD, max_affected=2)
    assert repo.bulk_update(filter=interns(), **DISCARD, max_affected=3)["would_affect"] == 3


def test_sample_shows_the_first_twenty(repo):
    for _ in range(25):
        add(repo)

    plan = repo.bulk_update(filter=interns(), **DISCARD)

    assert plan["would_affect"] == 25 and len(plan["sample"]) == 20


@pytest.mark.parametrize("call, message", [
    ({"status": "descartada", "discard_reason": "x"}, "filter.*ids"),
    ({"filter": {}, "status": "descartada", "discard_reason": "x"}, "ao menos um filtro"),
    ({"filter": {"status": "a_aplicar"}, "ids": [1], "status": "descartada", "discard_reason": "x"}, "filter.*ids"),
    ({"filter": {"status": "a_aplicar"}}, "Nada a alterar"),
    ({"filter": {"status": "a_aplicar"}, "status": "rh", "discard_reason": "x"}, "discard_reason"),
])
def test_invalid_calls(repo, call, message):
    with pytest.raises(VagasError, match=message):
        repo.bulk_update(**call)


async def test_tool_round_trip_through_mcp(server):
    async with Client(server) as client:
        for n in range(2):
            await client.call_tool("add_application", {
                "company": "Acme", "role": f"Data Scientist Intern {n}", "source": "gupy", "status": "a_aplicar",
                "seniority": "estagio", "url": f"https://acme.gupy.io/jobs/{n}"})
        args = {"filter": {"status": "a_aplicar", "seniority": ["estagio"]}, **DISCARD}
        plan = (await client.call_tool("bulk_update_applications", args)).structured_content
        done = (await client.call_tool("bulk_update_applications", {
            **args, "dry_run": False, "confirm_token": plan["confirm_token"]})).structured_content
        history = (await client.call_tool("get_history", {"id": done["ids"][0]})).structured_content
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert plan["would_affect"] == 2 and "url" in plan["sample"][0]
    assert done["updated"] == 2
    assert history["events"][-1]["to_status"] == "descartada"
    assert tools["bulk_update_applications"].annotations.destructive_hint is True
