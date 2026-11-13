"""Critérios de triagem mudaram: as vagas abertas são conferidas de novo pelas regras que não pedem julgamento."""

import json

import pytest
from mcp import Client

from resume_fixture import fictitious_resume
from vagas import settings_form
from vagas.db import connect
from vagas.repo import Repo
from vagas.resume_repo import ResumeStore
from vagas.server import build_server
from vagas.triage import Triage

pytestmark = pytest.mark.anyio

CRITERIA = """\
- Cargos alvo: data_scientist
- Empresas ignoradas: CI&T
- Termos de vaga exclusiva PcD: exclusiva para PcD
- Locais aceitos para híbrido e presencial: São Paulo
- Vagas afirmativas que posso disputar: {groups}
"""
WOMEN_ONLY = "Vaga exclusiva para mulheres. Modelos com Python e SQL."
PLAIN = "Modelos com Python e SQL."


@pytest.fixture
def files(tmp_path):
    (tmp_path / "criterios-triagem.md").write_text(CRITERIA.format(groups="nenhuma"), encoding="utf-8")
    return tmp_path


@pytest.fixture
def conn(db_path, files):
    c = connect(db_path)
    store = ResumeStore(c, files / "curriculo.yaml")
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    yield c
    c.close()


@pytest.fixture
def triage(conn, files):
    return Triage(conn, criteria_path=files / "criterios-triagem.md", draft_path=files / "curriculo.yaml")


def add(conn, n, description=PLAIN, status="a_aplicar", company="Acme", **extra):
    return Repo(conn).add_application(company=company, role="Cientista de Dados", source="gupy", status=status,
                                      url=f"https://acme.gupy.io/jobs/{n}", description=description,
                                      pending="CPF" if status == "pendente_usuario" else None, **extra)["application"]


def status(conn, app):
    return Repo(conn).get(app["id"])["status"]


def test_first_check_discards_open_jobs_that_the_criteria_reject(conn, triage):
    women = add(conn, 1, WOMEN_ONLY)
    pending = add(conn, 2, WOMEN_ONLY, status="pendente_usuario")
    applied = add(conn, 3, WOMEN_ONLY, status="aplicada")
    fine = add(conn, 4)

    result = triage.apply_criteria_changes()

    assert [d["id"] for d in result["discarded"]] == [women["id"], pending["id"]]
    assert "mulheres" in result["discarded"][0]["reason"] and result["discarded"][0]["url"] == women["url"]
    assert (status(conn, women), status(conn, pending), status(conn, applied), status(conn, fine)) == (
        "descartada", "descartada", "aplicada", "a_aplicar")
    events = Repo(conn).get_history(women["id"])["events"]
    assert "critérios de triagem mudaram" in events[-1]["note"]


def test_unchanged_criteria_do_not_recheck_so_a_reopened_job_stays_open(conn, triage):
    women = add(conn, 1, WOMEN_ONLY)
    triage.apply_criteria_changes()
    Repo(conn).update_application(women["id"], status="a_aplicar")

    assert triage.apply_criteria_changes() is None
    assert status(conn, women) == "a_aplicar"


def test_changed_criteria_recheck_open_jobs(conn, triage, files):
    triage.apply_criteria_changes()
    ignored = add(conn, 1, company="CI&T Brasil")
    women = add(conn, 2, WOMEN_ONLY)
    path = files / "criterios-triagem.md"
    path.write_text(CRITERIA.format(groups="mulheres").replace("CI&T", "CI&T Brasil"), encoding="utf-8")

    result = triage.apply_criteria_changes()

    assert [d["id"] for d in result["discarded"]] == [ignored["id"]]
    assert status(conn, women) == "a_aplicar"


def test_seniorities_and_states_outside_the_criteria_are_discarded(conn, triage, files):
    path = files / "criterios-triagem.md"
    path.write_text(CRITERIA.format(groups="nenhuma") + "- Senioridades buscadas: pleno\n"
                    "- Estados aceitos para híbrido e presencial: SP\n", encoding="utf-8")
    senior = add(conn, 1, seniority="senior")
    far = add(conn, 2, seniority="pleno", work_mode="hibrido", location="Curitiba, PR")
    remote = add(conn, 3, seniority="pleno", work_mode="remoto", location="Curitiba, PR")

    discarded = {d["id"]: d["reason"] for d in triage.apply_criteria_changes()["discarded"]}

    assert set(discarded) == {senior["id"], far["id"]}
    assert "senioridades" in discarded[senior["id"]] and "PR" in discarded[far["id"]]
    assert status(conn, remote) == "a_aplicar"


def test_missing_criteria_file_is_not_an_error(conn, files):
    add(conn, 1, WOMEN_ONLY)
    triage = Triage(conn, criteria_path=files / "nao-existe.md", draft_path=files / "curriculo.yaml")

    assert triage.apply_criteria_changes() is None


async def test_work_list_reports_the_recheck_once(db_path, files, monkeypatch):
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(files / "criterios-triagem.md"))
    async with Client(build_server(db_path, draft_path=files / "curriculo.yaml")) as client:
        await client.call_tool("add_application", {"company": "Acme", "role": "DS", "source": "gupy",
                                                   "status": "a_aplicar", "description": WOMEN_ONLY})
        first = (await client.call_tool("work_list", {})).structured_content
        again = (await client.call_tool("work_list", {})).structured_content
        tools = {t.name: t for t in (await client.list_tools()).tools}

    [row] = first["criteria_recheck"]["discarded"]
    assert row["company"] == "Acme" and "mulheres" in row["reason"]
    assert first["counts"] == {"ready": 0, "pending": 0}
    assert "criteria_recheck" not in again
    assert "criteria_recheck" in tools["work_list"].description


def test_saving_the_criteria_in_the_panel_rechecks_at_once(db_path, files, monkeypatch, conn):
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(files / "criterios-triagem.md"))
    monkeypatch.setenv("VAGAS_MASTER_RESUME", str(files / "curriculo.yaml"))
    path = files / "criterios-triagem.md"
    path.write_text(CRITERIA.format(groups="mulheres"), encoding="utf-8")
    women = add(conn, 1, WOMEN_ONLY)

    result = settings_form.save({"criteria": {"Vagas afirmativas que posso disputar": []}}, db_path)

    assert result["saved"], result["errors"]
    assert [d["id"] for d in result["rechecked"]["discarded"]] == [women["id"]]
    assert status(conn, women) == "descartada"
    assert json.dumps(result["rechecked"], ensure_ascii=False)
