"""O servidor conta a atualização automática no get_config e pode tê-la desligada pelo config.toml."""

import pytest
from mcp import Client

from vagas import auto_update
from vagas.config import resolve, set_value
from vagas.server import build_server

pytestmark = pytest.mark.anyio


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content


async def test_get_config_tells_what_the_update_changed(db_path):
    report = {"status": "atualizado", "from": "abc1234", "to": "def5678",
              "actions": ["Abra uma conversa nova para usar a versão nova do MCP."]}
    async with Client(build_server(db_path, update_status=lambda: report)) as client:
        result = payload(await client.call_tool("get_config", {}))
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert result["update"] == report
    assert "update" in tools["get_config"].description


async def test_get_config_without_news_has_no_update_field(db_path):
    async with Client(build_server(db_path, update_status=lambda: None)) as client:
        result = payload(await client.call_tool("get_config", {}))

    assert "update" not in result


def test_auto_update_is_on_by_default_and_can_be_turned_off(db_path):
    assert resolve("auto_update", db_path) == ("sim", "default")

    set_value("auto_update", "desligado", db_path)

    assert resolve("auto_update", db_path) == ("nao", "config")
    assert auto_update.start(db_path) is None


async def test_server_instructions_ask_for_get_config_at_the_start_of_each_conversation(db_path):
    async with Client(build_server(db_path)) as client:
        instructions = client.instructions

    assert "começo de cada conversa" in instructions and "update" in instructions
