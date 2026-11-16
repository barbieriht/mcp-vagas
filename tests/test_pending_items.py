"""Pendências estruturadas: itens {kind, field, options?} ao lado do texto livre, agrupados entre as vagas e limpos
sozinhos quando a resposta entra no perfil."""

import pytest
from mcp import Client

from test_sensitive import FakeBackend
from vagas import settings_form
from vagas.jobs_view import list_jobs
from vagas.repo import VagasError
from vagas.sensitive import Vault
from vagas.server import build_server

pytestmark = pytest.mark.anyio

ATTACH = {"kind": "anexo_curriculo", "field": "Resume_Acme.pdf"}
SHIRT = {"kind": "resposta_aberta", "field": "Tamanho de camiseta (opções P, M)", "options": ["P", "M"]}
DISABILITY = {"kind": "diversidade", "field": "Possui deficiência"}


def pending_app(repo, n, items, pending=None):
    app = repo.add_application(company=f"Empresa {n}", role="Cientista de Dados", source="gupy", status="a_aplicar",
                               url=f"https://empresa{n}.gupy.io/jobs/{n}")["application"]
    return repo.update_application(app["id"], status="pendente_usuario", pending=pending, pending_items=items)


def test_items_are_stored_validated_and_cleared(repo):
    app = pending_app(repo, 1, [ATTACH, SHIRT], pending="revisar e enviar")

    assert app["pending_items"] == [ATTACH, SHIRT] and app["pending"] == "revisar e enviar"
    with pytest.raises(VagasError, match="anexo_curriculo"):
        repo.update_application(app["id"], pending_items=[{"kind": "outra coisa", "field": "x"}])
    with pytest.raises(VagasError, match="field"):
        repo.update_application(app["id"], pending_items=[{"kind": "login", "field": " "}])
    assert repo.update_application(app["id"], pending_items=[])["pending_items"] is None


def test_waiting_for_the_user_needs_a_text_or_items(repo):
    app = pending_app(repo, 1, [ATTACH])

    assert app["status"] == "pendente_usuario" and app["pending"] is None
    other = repo.add_application(company="X", role="Y", source="gupy", status="a_aplicar")["application"]
    with pytest.raises(VagasError, match="pending"):
        repo.update_application(other["id"], status="pendente_usuario")


def test_equal_pendings_are_grouped_across_jobs(repo):
    a = pending_app(repo, 1, [ATTACH, SHIRT])
    b = pending_app(repo, 2, [{"kind": "anexo_curriculo", "field": "Resume_Beta.pdf"}, SHIRT])
    c = pending_app(repo, 3, [{"kind": "anexo_curriculo", "field": "Resume_Gama.pdf"}, DISABILITY])

    groups = repo.pending_groups()

    assert groups[0] == {"kind": "anexo_curriculo", "label": "anexar currículo", "count": 3,
                         "ids": [a["id"], b["id"], c["id"]]}
    assert groups[1] == {"kind": "resposta_aberta", "field": SHIRT["field"],
                         "label": f"responder: {SHIRT['field']}", "count": 2, "ids": [a["id"], b["id"]]}
    assert groups[2]["kind"] == "diversidade" and groups[2]["count"] == 1


def test_only_pending_also_finds_jobs_with_items_only(repo):
    app = pending_app(repo, 1, [ATTACH])

    assert [a["id"] for a in repo.list_applications(only_pending=True)["applications"]] == [app["id"]]


PERFIL = """\
# Dados para formulários

## Respostas padrão
- Tamanho de camiseta (opções P, M): <PREENCHER>

## Diversidade e inclusão
- Possui deficiência: <PREENCHER>

## Outros campos de formulário
- CPF: informar manualmente
"""


@pytest.fixture
def skill(tmp_path, monkeypatch):
    folder = tmp_path / "skill"
    folder.mkdir()
    (folder / "perfil.md").write_text(PERFIL, encoding="utf-8")
    (folder / "perfil.example.md").write_text(PERFIL, encoding="utf-8")
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(folder))
    return folder


async def test_an_answer_saved_in_the_profile_clears_the_items_it_resolves(db_path, repo, skill):
    a = pending_app(repo, 1, [ATTACH, SHIRT])
    b = pending_app(repo, 2, [SHIRT, DISABILITY])
    async with Client(build_server(db_path, vault=Vault(skill / "cofre.json", FakeBackend()))) as client:
        saved = (await client.call_tool("add_profile_field", {"label": SHIRT["field"], "value": "M"})).structured_content
        listed = (await client.call_tool("list_applications", {"status": "pendente_usuario"})).structured_content
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert sorted(saved["resolved_pending"]) == sorted([a["id"], b["id"]])
    assert repo.get(a["id"])["pending_items"] == [ATTACH]
    assert repo.get(b["id"])["pending_items"] == [DISABILITY]
    assert repo.get(a["id"])["status"] == "pendente_usuario"  # o formulário ainda espera o resto
    assert [g["label"] for g in listed["pending_groups"]] == ["anexar currículo", "diversidade: Possui deficiência"]
    kinds = tools["update_application"].input_schema["$defs"]["PendingItem"]["properties"]["kind"]["enum"]
    assert "anexo_curriculo" in kinds and "consentimento" in kinds


def test_saving_the_profile_in_the_panel_also_clears_resolved_items(db_path, repo, skill):
    app = pending_app(repo, 1, [DISABILITY, ATTACH])

    result = settings_form.save({"profile": {"Diversidade e inclusão/Possui deficiência": "Não"}}, db_path)

    assert result["saved"], result["errors"]
    assert repo.get(app["id"])["pending_items"] == [ATTACH]


def test_the_jobs_page_shows_the_groups_and_the_extension(db_path, repo, conn_for_jobs):
    pending_app(repo, 1, [ATTACH])

    data = list_jobs(conn_for_jobs, {}, db_path=db_path)

    assert data["pending_groups"][0]["label"] == "anexar currículo"
    assert data["extension"]["known"] is False and data["extension"]["reason"]


@pytest.fixture
def conn_for_jobs(db_path):
    from vagas.db import connect

    conn = connect(db_path)
    yield conn
    conn.close()
