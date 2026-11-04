import pytest
from mcp import Client

from vagas.server import build_server

pytestmark = pytest.mark.anyio

SCHEMA_VALUES = ("default", "enum", "const", "examples")


def schema_titles(node, in_properties=False):
    """Todo `title` de nível de schema (o rótulo que o pydantic gera); campos chamados title não contam."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "title" and isinstance(value, str) and not in_properties:
                found.append(value)
            elif key not in SCHEMA_VALUES:
                found += schema_titles(value, in_properties=key in ("properties", "$defs"))
    elif isinstance(node, list):
        for item in node:
            found += schema_titles(item)
    return found


async def tools(db_path):
    async with Client(build_server(db_path)) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


async def test_schemas_carry_no_redundant_titles(db_path):
    leftovers = {name: schema_titles(t.input_schema) for name, t in (await tools(db_path)).items()}

    assert {name: titles for name, titles in leftovers.items() if titles} == {}


async def test_fields_named_title_are_kept(db_path):
    listed = await tools(db_path)

    assert "title" in listed["score_job_match"].input_schema["properties"]
    defs = listed["create_tailored_resume"].input_schema["$defs"].values()
    assert any("title" in d.get("properties", {}) for d in defs)


async def test_schemas_keep_required_fields_enums_and_descriptions(db_path):
    schema = (await tools(db_path))["add_application"].input_schema

    assert set(schema["required"]) >= {"company", "role"}
    assert "linkedin" in schema["properties"]["source"]["enum"]
    assert schema["properties"]["status"]["default"] == "aplicada"
