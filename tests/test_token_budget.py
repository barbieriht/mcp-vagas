"""O que as tools custam em contexto: definições enxutas e respostas sem campos que o fluxo não usa.

A descrição da vaga (milhares de caracteres) e a avaliação salarial completa só saem em get_history;
listas, buscas e retornos de gravação trazem o resumo, sem campos vazios.
"""

import json

import pytest
from mcp import Client

from vagas.server import build_server

pytestmark = pytest.mark.anyio

DESCRIPTION = "Requisitos: Python, SQL e estatística. " * 100
HEAVY = {"description", "company_norm", "url_canonical"}


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content


async def add(client, n, **extra):
    fields = {"company": "Acme", "role": f"Cientista de Dados {n}", "source": "gupy",
              "url": f"https://acme.gupy.io/jobs/{n}", "description": DESCRIPTION, **extra}
    return payload(await client.call_tool("add_application", fields))["application"]


async def test_descriptions_carry_no_docstring_indentation(server):
    async with Client(server) as client:
        tools = (await client.list_tools()).tools

    assert [t.name for t in tools if "\n    " in t.description] == []


async def test_optional_parameters_are_not_spelled_as_nullable(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    url = tools["add_application"].input_schema["properties"]["url"]
    assert url == {"type": "string"}
    assert "null" not in json.dumps(tools["update_application"].input_schema)
    # o default informativo continua: omitir o status ainda significa "aplicada"
    assert tools["add_application"].input_schema["properties"]["status"]["default"] == "aplicada"


async def test_optional_parameter_still_accepts_an_explicit_null(server):
    async with Client(server) as client:
        added = await add(client, 1)
        result = payload(await client.call_tool("update_application", {"id": added["id"], "note": "x",
                                                                       "pending": None}))

    assert result["id"] == added["id"]


async def test_list_returns_summaries_without_the_job_text(server):
    async with Client(server) as client:
        added = await add(client, 1, status="pendente_usuario", pending="CPF")
        listed = payload(await client.call_tool("list_applications", {}))
        history = payload(await client.call_tool("get_history", {"id": added["id"]}))

    [row] = listed["applications"]
    assert HEAVY.isdisjoint(row) and "salary_evaluation" not in row
    assert None not in row.values()
    assert row["id"] == added["id"] and row["pending"] == "CPF" and row["url"] == "https://acme.gupy.io/jobs/1"
    assert row["last_event_at"]
    assert history["application"]["description"] == DESCRIPTION


async def test_list_is_paginated(server):
    async with Client(server) as client:
        for n in range(3):
            await add(client, n)
        first = payload(await client.call_tool("list_applications", {"limit": 2}))
        rest = payload(await client.call_tool("list_applications", {"limit": 2, "offset": first["next_offset"]}))

    assert [len(first["applications"]), first["count"], first["next_offset"]] == [2, 3, 2]
    assert [len(rest["applications"]), rest["count"]] == [1, 3] and "next_offset" not in rest
    ids = [a["id"] for a in first["applications"] + rest["applications"]]
    assert len(set(ids)) == 3


async def test_find_by_company_returns_summaries(server):
    async with Client(server) as client:
        for n in range(3):
            await add(client, n)
        found = payload(await client.call_tool("find_application", {"company": "ACME"}))

    assert len(found["matches"]) == 3
    assert all(HEAVY.isdisjoint(m) and m["status"] == "aplicada" for m in found["matches"])


async def test_writes_do_not_echo_the_job_text(server):
    async with Client(server) as client:
        added = await add(client, 1)
        again = payload(await client.call_tool("add_application", {
            "company": "Acme", "role": "x", "source": "gupy", "url": "https://acme.gupy.io/jobs/1"}))
        updated = payload(await client.call_tool("update_application", {"id": added["id"], "note": "ok"}))

    assert HEAVY.isdisjoint(added) and HEAVY.isdisjoint(again["application"]) and HEAVY.isdisjoint(updated)
    assert again["created"] is False and again["application"]["id"] == added["id"]
    assert updated["status"] == "aplicada"


async def test_text_content_is_compact_json_of_the_structured_result(server):
    async with Client(server) as client:
        await add(client, 1)
        result = await client.call_tool("list_applications", {})

    text = result.content[0].text
    assert json.loads(text) == result.structured_content
    assert "\n" not in text and ": " not in text.replace(DESCRIPTION, "")


async def test_work_list_rows_omit_empty_fields(db_path, tmp_path):
    async with Client(build_server(db_path, draft_path=tmp_path / "c.yaml")) as client:
        await client.call_tool("add_application", {"company": "Alfa", "role": "DS", "source": "gupy",
                                                   "status": "a_aplicar", "work_mode": "remoto"})
        result = payload(await client.call_tool("work_list", {}))

    [row] = result["pending"]
    assert row["company"] == "Alfa" and row["pending"]
    assert all(value not in (None, [], {}) for value in row.values())


async def test_get_config_explains_only_what_still_needs_setup(db_path, monkeypatch, tmp_path):
    monkeypatch.setenv("VAGAS_RESUME_OUT", str(tmp_path / "pdfs"))
    async with Client(build_server(db_path)) as client:
        await client.call_tool("set_config", {"key": "export_dir"})
        result = payload(await client.call_tool("get_config", {}))

    settings = result["settings"]
    assert "login_email" in result["needs_setup"] and settings["login_email"]["description"]
    assert "description" not in settings["export_dir"] and settings["export_dir"]["source"] == "config"
    assert settings["resume_out"]["env"] == "VAGAS_RESUME_OUT" and "env" not in settings["export_dir"]
    assert settings["login_method"]["choices"] == ["linkedin", "google"]
    assert all(value not in (None, [], {}) for entry in settings.values() for value in entry.values())
