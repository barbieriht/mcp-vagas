import json
import sys

import pytest
from mcp import Client, StdioServerParameters

from vagas.models import SOURCES, WORK_MODES

pytestmark = pytest.mark.anyio

LINKEDIN = "https://www.linkedin.com/jobs/view/4012345678/"


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content


async def tools_by_name(client):
    return {tool.name: tool for tool in (await client.list_tools()).tools}


async def test_tools_are_listed_with_docstrings(server):
    async with Client(server) as client:
        tools = await tools_by_name(client)

    assert {"add_application", "find_application"} <= tools.keys()
    assert "SEMPRE" in tools["find_application"].description
    assert all(tool.description for tool in tools.values())


async def test_enums_are_visible_in_add_application_schema(server):
    async with Client(server) as client:
        schema = (await tools_by_name(client))["add_application"].input_schema

    text = json.dumps(schema)
    assert all(value in text for value in SOURCES + WORK_MODES)
    assert {"company", "role", "source"} <= set(schema["required"])


async def test_add_then_find_by_url(server):
    async with Client(server) as client:
        added = payload(await client.call_tool("add_application", {
            "company": "Nubank", "role": "Data Scientist", "url": LINKEDIN, "source": "linkedin",
        }))
        found = payload(await client.call_tool("find_application", {"url": LINKEDIN + "#x"}))

    assert added["created"] is True
    assert added["application"]["status"] == "aplicada"
    assert found["matches"] == [added["application"]]


async def test_duplicate_returns_existing_record(server):
    args = {"company": "Nubank", "role": "Data Scientist", "url": LINKEDIN, "source": "linkedin"}
    async with Client(server) as client:
        first = payload(await client.call_tool("add_application", args))
        second = payload(await client.call_tool("add_application", args))

    assert second["created"] is False
    assert second["application"] == first["application"]


async def test_invalid_enum_is_a_readable_error(server):
    async with Client(server) as client:
        result = await client.call_tool("add_application", {
            "company": "Nubank", "role": "DS", "source": "monster",
        })

    assert result.is_error
    assert "source" in result.content[0].text
    assert "Traceback" not in result.content[0].text


async def test_domain_error_message_reaches_the_client(server):
    async with Client(server) as client:
        result = await client.call_tool("add_application", {
            "company": "   ", "role": "DS", "source": "linkedin",
        })

    assert result.is_error
    assert "company" in result.content[0].text


async def test_find_without_criteria_is_a_readable_error(server):
    async with Client(server) as client:
        result = await client.call_tool("find_application", {})

    assert result.is_error
    assert "url" in result.content[0].text


async def test_stdio_server_starts_and_keeps_stdout_clean(db_path):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "vagas.server"], env={"VAGAS_DB": str(db_path)},
    )
    async with Client(params) as client:
        tools = await tools_by_name(client)
        added = payload(await client.call_tool("add_application", {
            "company": "Nubank", "role": "DS", "url": LINKEDIN, "source": "linkedin",
        }))

    assert "find_application" in tools
    assert added["created"] is True
    assert db_path.exists()


async def test_find_docstring_explains_pending_versus_other_statuses(server):
    async with Client(server) as client:
        description = (await tools_by_name(client))["find_application"].description

    assert "pendente_usuario" in description
    assert "retomar" in description.lower()


async def test_initial_status_enum_is_visible_in_schema(server):
    async with Client(server) as client:
        schema = json.dumps((await tools_by_name(client))["add_application"].input_schema)

    assert all(s in schema for s in ("aplicada", "pendente_usuario", "descartada"))
    assert "tecnica" not in schema


async def test_pending_and_discarded_via_mcp(server):
    base = {"role": "DS", "source": "linkedin"}
    async with Client(server) as client:
        pending = payload(await client.call_tool("add_application", {
            **base, "company": "Itaú", "url": "https://x.com/1",
            "status": "pendente_usuario", "pending": "CPF",
        }))
        discarded = payload(await client.call_tool("add_application", {
            **base, "company": "CI&T", "url": "https://x.com/2",
            "status": "descartada", "discard_reason": "Empresa ignorada",
        }))
        missing = await client.call_tool("add_application", {
            **base, "company": "Itaú", "url": "https://x.com/3", "status": "pendente_usuario",
        })
        found = payload(await client.call_tool("find_application", {"url": "https://x.com/2"}))

    assert pending["application"]["pending"] == "CPF"
    assert found["matches"][0]["discard_reason"] == "Empresa ignorada"
    assert missing.is_error and "pending" in missing.content[0].text


async def test_update_and_history_via_mcp(server):
    async with Client(server) as client:
        app = payload(await client.call_tool("add_application", {
            "company": "Nubank", "role": "DS", "source": "linkedin",
            "status": "pendente_usuario", "pending": "CPF",
        }))["application"]
        updated = payload(await client.call_tool("update_application", {
            "id": app["id"], "status": "aplicada", "pending": "", "note": "CPF enviado",
        }))
        same = await client.call_tool("update_application", {"id": app["id"], "status": "aplicada"})
        history = payload(await client.call_tool("get_history", {"id": app["id"]}))
        missing = await client.call_tool("get_history", {"id": 999})
        tools = await tools_by_name(client)

    assert (updated["status"], updated["pending"]) == ("aplicada", None)
    assert same.is_error and "já está" in same.content[0].text
    assert [e["to_status"] for e in history["events"]] == ["pendente_usuario", "aplicada"]
    assert history["events"][-1]["note"] == "CPF enviado"
    assert missing.is_error and "999" in missing.content[0].text
    assert "tecnica" in json.dumps(tools["update_application"].input_schema)


async def test_master_resume_lifecycle_via_mcp(server, db_path):
    from resume_fixture import fictitious_resume

    async with Client(server) as client:
        tools = await tools_by_name(client)
        before = await client.call_tool("get_master_resume", {})
        saved = payload(await client.call_tool("save_master_draft", {"resume": fictitious_resume()}))
        approved = payload(await client.call_tool("approve_master", {}))
        master = payload(await client.call_tool("get_master_resume", {}))

    assert "explicitamente" in tools["approve_master"].description
    assert "experience" in json.dumps(tools["save_master_draft"].input_schema)
    assert before.is_error and "save_master_draft" in before.content[0].text
    assert saved["path"] == str(db_path.parent / "curriculo.yaml")
    assert master["version_id"] == approved["version_id"]
    assert master["resume"]["basics"]["name"] == "Fulana de Tal"


async def test_invalid_master_draft_is_a_readable_error_via_mcp(server):
    from resume_fixture import fictitious_resume

    resume = fictitious_resume()
    resume["experience"][1]["paragraphs"][0]["id"] = "exp-acme-tech-lead-p1"
    async with Client(server) as client:
        result = await client.call_tool("save_master_draft", {"resume": resume})

    assert result.is_error
    assert "exp-acme-tech-lead-p1" in result.content[0].text


async def test_render_master_resume_via_mcp(db_path, tmp_path, monkeypatch):
    from resume_fixture import fictitious_resume
    from vagas.server import build_server

    monkeypatch.delenv("VAGAS_RESUME_OUT", raising=False)
    without_out = build_server(db_path)
    with_out = build_server(db_path, resume_out=tmp_path / "out")

    async with Client(with_out) as client:
        not_approved = await client.call_tool("render_master_resume", {})
        await client.call_tool("save_master_draft", {"resume": fictitious_resume()})
        await client.call_tool("approve_master", {})
        rendered = payload(await client.call_tool("render_master_resume", {"label": "Geral"}))
    async with Client(without_out) as client:
        unconfigured = await client.call_tool("render_master_resume", {})

    assert not_approved.is_error and "approve_master" in not_approved.content[0].text
    assert rendered["path"] == str(tmp_path / "out" / "Fulana_Tal_Resume_Geral.pdf")
    assert rendered["pages"] == 1
    assert unconfigured.is_error and "VAGAS_RESUME_OUT" in unconfigured.content[0].text


async def test_tailored_resume_via_mcp(db_path, tmp_path):
    from resume_fixture import fictitious_resume
    from vagas.server import build_server

    server = build_server(db_path, resume_out=tmp_path / "out")
    good = {"label": "Nubank", "sections": [{"section": "experience", "items": [
        {"id": "exp-acme-tech-lead", "paragraphs": [
            {"id": "exp-acme-tech-lead-p1", "bullets": ["Cut answer latency by 30%"]}]}]}]}
    bad = {"sections": [{"section": "experience", "items": [
        {"id": "exp-acme-tech-lead", "paragraphs": [
            {"id": "exp-acme-tech-lead-p1", "bullets": ["Cut answer latency by 45%"]}]}]}]}

    async with Client(server) as client:
        await client.call_tool("save_master_draft", {"resume": fictitious_resume()})
        await client.call_tool("approve_master", {})
        tools = await tools_by_name(client)
        created = payload(await client.call_tool("create_tailored_resume", {"selection": good}))
        rejected = await client.call_tool("create_tailored_resume", {"selection": bad})
        listed = payload(await client.call_tool("list_resumes", {}))
        fetched = payload(await client.call_tool("get_resume", {"id": created["id"]}))

    assert "nunca" in tools["create_tailored_resume"].description.lower()
    assert created["path"].endswith("Fulana_Tal_Resume_Nubank.pdf")
    assert rejected.is_error and "45%" in rejected.content[0].text
    assert [r["id"] for r in listed["resumes"]] == [created["id"]]
    assert fetched["resolved"]["experience"][0]["company"] == "Acme Analytics"
