import itertools

import pytest

from vagas.db import connect
from vagas.repo import Repo, VagasError


@pytest.fixture
def repo(db_path):
    ticks = itertools.count()
    conn = connect(db_path)
    yield Repo(conn, now=lambda: f"2026-10-27T12:00:{next(ticks):02d}+00:00")
    conn.close()


def add(repo, **overrides):
    fields = dict(company="Nubank", role="Data Scientist", source="linkedin")
    fields.update(overrides)
    return repo.add_application(**fields)["application"]


def transitions(repo, app_id):
    return [(e["from_status"], e["to_status"], e["note"]) for e in repo.events(app_id)]


def test_status_change_records_event_with_note(repo):
    app = add(repo)

    updated = repo.update_application(app["id"], status="rh", note="Recrutadora: Ana")

    assert updated["status"] == "rh"
    assert transitions(repo, app["id"]) == [
        (None, "aplicada", None),
        ("aplicada", "rh", "Recrutadora: Ana"),
    ]


def test_updated_at_changes(repo):
    app = add(repo)

    updated = repo.update_application(app["id"], status="tecnica")

    assert updated["updated_at"] > app["updated_at"]
    assert updated["created_at"] == app["created_at"]


def test_same_status_is_rejected(repo):
    app = add(repo)

    with pytest.raises(VagasError, match="já está"):
        repo.update_application(app["id"], status="aplicada")


@pytest.mark.parametrize("target", ["tecnica", "proposta", "recusada", "desistiu", "rh"])
def test_any_transition_between_valid_statuses_is_allowed(repo, target):
    app = add(repo)
    repo.update_application(app["id"], status="gestor")

    assert repo.update_application(app["id"], status=target)["status"] == target


def test_invalid_status_is_rejected(repo):
    app = add(repo)

    with pytest.raises(VagasError, match="status"):
        repo.update_application(app["id"], status="entrevista")


def test_completing_a_pending_application(repo):
    app = add(repo, status="pendente_usuario", pending="CPF")

    updated = repo.update_application(app["id"], status="aplicada", pending="")

    assert (updated["status"], updated["pending"]) == ("aplicada", None)
    assert transitions(repo, app["id"])[-1] == ("pendente_usuario", "aplicada", None)


def test_note_without_status_change_records_event(repo):
    app = add(repo)

    repo.update_application(app["id"], note="Recrutador respondeu por e-mail")

    assert transitions(repo, app["id"])[-1] == ("aplicada", "aplicada", "Recrutador respondeu por e-mail")


def test_pending_can_change_without_status(repo):
    app = add(repo)
    repo.update_application(app["id"], status="tecnica")

    updated = repo.update_application(app["id"], pending="Teste técnico até sexta")

    assert (updated["status"], updated["pending"]) == ("tecnica", "Teste técnico até sexta")
    assert repo.update_application(app["id"], pending="")["pending"] is None


def test_moving_to_pending_requires_pending_text(repo):
    app = add(repo)

    with pytest.raises(VagasError, match="pending"):
        repo.update_application(app["id"], status="pendente_usuario")


def test_moving_to_discarded_requires_reason(repo):
    app = add(repo)

    with pytest.raises(VagasError, match="discard_reason"):
        repo.update_application(app["id"], status="descartada")

    updated = repo.update_application(app["id"], status="descartada", discard_reason="Salário abaixo")
    assert updated["discard_reason"] == "Salário abaixo"


def test_leaving_discarded_clears_reason(repo):
    app = add(repo, status="descartada", discard_reason="CI&T")

    updated = repo.update_application(app["id"], status="aplicada")

    assert updated["discard_reason"] is None


def test_discard_reason_without_moving_to_discarded_is_rejected(repo):
    app = add(repo)

    with pytest.raises(VagasError, match="discard_reason"):
        repo.update_application(app["id"], discard_reason="x")


def test_update_without_changes_is_rejected(repo):
    app = add(repo)

    with pytest.raises(VagasError, match="Nada a atualizar"):
        repo.update_application(app["id"])


def test_unknown_id_is_rejected(repo):
    with pytest.raises(VagasError, match="999"):
        repo.update_application(999, status="rh")


def test_history_is_chronological_starting_with_creation(repo):
    app = add(repo)
    repo.update_application(app["id"], status="rh")
    repo.update_application(app["id"], note="Entrevista marcada")
    repo.update_application(app["id"], status="tecnica")

    history = repo.get_history(app["id"])

    assert history["application"]["status"] == "tecnica"
    assert [(e["from_status"], e["to_status"]) for e in history["events"]] == [
        (None, "aplicada"), ("aplicada", "rh"), ("rh", "rh"), ("rh", "tecnica"),
    ]


def test_history_of_unknown_id_is_rejected(repo):
    with pytest.raises(VagasError, match="999"):
        repo.get_history(999)


def test_set_seniority_validates_and_logs(repo):
    app = repo.add_application(company="Acme", role="Cientista de Dados", source="gupy", status="a_aplicar")["application"]

    updated = repo.set_seniority(app["id"], "pleno", "4+ anos de experiência pedidos")

    assert updated["seniority"] == "pleno"
    assert repo.events(app["id"])[-1]["note"] == "Senioridade: pleno (4+ anos de experiência pedidos)."
    with pytest.raises(VagasError, match="seniority"):
        repo.set_seniority(app["id"], "mestre", "x")
