"""Situação da extensão do Chrome vista pelo MCP: última atividade, versão e o que ela preencheu por candidatura."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from mcp import Client

from test_sensitive import FakeBackend
from vagas.autofill import EXTENSION_VERSION, Applications, Approvals, Autofill, ExtensionStatus, extension_report
from vagas.db import connect
from vagas.repo import Repo
from vagas.sensitive import Vault
from vagas.server import build_server

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)
CPF = {"id": "c", "text": "CPF", "attrs": "cpf"}
RESUME = {"id": "f", "kind": "file", "text": "Anexe seu currículo", "accept": ".pdf"}


@pytest.fixture
def autofill(db_path, tmp_path):
    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    vault.set("cpf", "529.982.247-25")
    apps = Applications(db_path)
    return Autofill(vault, Approvals(tmp_path / "aprovacoes.json"), log_path=tmp_path / "autofill.log",
                    open_sites=apps.sites, extra_domains=lambda: [], resumes=apps.with_resumes,
                    status_path=tmp_path / "autofill_status.json")


def status(tmp_path):
    return json.loads((tmp_path / "autofill_status.json").read_text(encoding="utf-8"))


def test_every_request_records_activity_and_version_without_values(autofill, tmp_path):
    autofill.handle({"url": "https://acme.gupy.io/jobs/1", "fields": [CPF], "confirm": "once", "version": "1.3.0"})

    saved = status(tmp_path)
    assert saved["version"] == "1.3.0" and saved["last_seen"]
    assert saved["recent"][0]["host"] == "acme.gupy.io" and saved["recent"][0]["status"] == "filled"
    assert saved["recent"][0]["fields"] == {"documentos": 1}
    assert "529" not in (tmp_path / "autofill_status.json").read_text(encoding="utf-8")


def test_repeated_retries_become_one_line_with_a_count(autofill, tmp_path):
    for _ in range(5):  # o campo de currículo sem PDF é consultado de novo a cada poucos segundos
        autofill.handle({"url": "https://jobs.smartrecruiters.com/Acme/1", "fields": [RESUME], "confirm": None})

    recent = status(tmp_path)["recent"]
    assert len(recent) == 1 and recent[0]["count"] == 5
    assert recent[0]["status"] == "nothing" and recent[0]["fields"] == {"curriculo": 1}
    assert recent[0]["resume"] == "nao_encontrado"


def test_a_broken_status_file_never_breaks_the_fill(autofill, tmp_path):
    (tmp_path / "autofill_status.json").write_text("{quebrado", encoding="utf-8")

    response = autofill.handle({"url": "https://acme.gupy.io/jobs/1", "fields": [CPF], "confirm": "once"})

    assert response["status"] == "filled"


def test_without_any_trace_the_status_is_unknown(tmp_path, db_path):
    report = extension_report(tmp_path / "autofill_status.json", tmp_path / "autofill.log", db_path, now=NOW)

    assert report["known"] is False and report["reason"]


def write_log(tmp_path, *entries):
    with (tmp_path / "autofill.log").open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def test_the_report_tells_what_was_filled_per_application(tmp_path, db_path):
    conn = connect(db_path)
    repo = Repo(conn)
    gupy = repo.add_application(company="Acme", role="Cientista de Dados", source="gupy", status="a_aplicar",
                                url="https://acme.gupy.io/jobs/1")["application"]
    linkedin = repo.add_application(company="Beta", role="ML Engineer", source="linkedin", status="aplicada",
                                    url="https://www.linkedin.com/jobs/view/4012345678/")["application"]
    repo.add_application(company="Gama", role="Analista", source="gupy", status="a_aplicar",
                         url="https://gama.gupy.io/jobs/3")
    conn.close()
    at = (NOW - timedelta(hours=2)).isoformat()
    write_log(tmp_path,
              {"at": at, "host": "acme.gupy.io", "key": "acme.gupy.io", "documents": ["CPF"], "mode": "once",
               "terms": ["Li e aceito a política de privacidade"]},
              {"at": at, "host": "www.linkedin.com", "key": "linkedin.com/vaga/4012345678", "documents": [],
               "mode": "once", "resume": {"application_id": linkedin["id"], "name": "Beta.pdf"}})
    ExtensionStatus(tmp_path / "autofill_status.json").write(
        {"last_seen": at, "version": EXTENSION_VERSION, "recent": []})

    report = extension_report(tmp_path / "autofill_status.json", tmp_path / "autofill.log", db_path, now=NOW)

    assert report["known"] and report["outdated"] is False and report["idle_hours"] == 2
    by_id = {a["id"]: a for a in report["applications"]}
    assert set(by_id) == {gupy["id"], linkedin["id"]}
    assert by_id[gupy["id"]]["documents"] == ["CPF"] and by_id[gupy["id"]]["terms"] == 1
    assert by_id[linkedin["id"]]["resume"] == "Beta.pdf"


def test_an_old_extension_is_flagged_as_outdated(tmp_path, db_path):
    write_log(tmp_path, {"at": (NOW - timedelta(days=9)).isoformat(), "host": "acme.gupy.io", "key": "acme.gupy.io",
                         "documents": ["CPF"], "mode": "once"})

    report = extension_report(tmp_path / "autofill_status.json", tmp_path / "autofill.log", db_path, now=NOW)

    assert report["known"] and report["version"] is None and report["outdated"] is True
    assert report["idle_hours"] == 9 * 24 and report["warnings"]


def test_the_manifest_version_is_the_one_the_mcp_expects():
    from pathlib import Path

    manifest = Path(__file__).resolve().parents[1] / "extension" / "manifest.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == EXTENSION_VERSION
    background = (manifest.parent / "background.js").read_text(encoding="utf-8")
    assert "getManifest().version" in background


async def test_the_tool_reports_the_extension(db_path):
    async with Client(build_server(db_path)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        result = (await client.call_tool("extension_status", {})).structured_content

    assert result["known"] is False
    assert "lote" in tools["extension_status"].description
