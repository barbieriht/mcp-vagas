"""Anotações das tools (readOnlyHint, destructiveHint, openWorldHint).

O Claude Desktop e o claude.ai agrupam as tools de um conector por elas ("só leitura" e "escrita") e deixam o
usuário aprovar cada grupo de uma vez; sem anotação, toda tool conta como escrita destrutiva e pede permissão.
"""

import pytest
from mcp import Client

pytestmark = pytest.mark.anyio

READ_ONLY = {
    "settings_link", "get_config", "find_application", "list_applications", "get_history", "extract_resume_text",
    "get_profile", "extension_status", "diff_master", "get_master_resume", "suggest_tailored_selection",
    "read_job_posting", "score_job_match", "list_resumes", "get_resume", "find_salary_estimate", "find_job_search",
    "work_list", "get_search_run", "suggest_job_searches", "query_applications", "list_referrals",
}
DESTRUCTIVE = {"update_application", "bulk_update_applications", "discard_salary_estimate", "apply_profile_migration",
               "save_master_draft", "add_referral", "remove_referral"}
OPEN_WORLD = {"read_job_posting", "triage_job", "search_jobs", "start_search_run", "import_linkedin_profile"}


async def tools(server):
    async with Client(server) as client:
        return {tool.name: tool for tool in (await client.list_tools()).tools}


async def test_every_tool_says_whether_it_only_reads(server):
    listed = await tools(server)

    assert {name for name, tool in listed.items() if tool.annotations is None
            or tool.annotations.read_only_hint is None} == set()
    assert {name for name, tool in listed.items() if tool.annotations.read_only_hint} == READ_ONLY


async def test_writes_that_only_add_are_not_destructive(server):
    listed = await tools(server)

    writes = {name: tool.annotations for name, tool in listed.items() if name not in READ_ONLY}
    assert {name for name, notes in writes.items() if notes.destructive_hint} == DESTRUCTIVE
    assert {"add_application", "save_salary_estimate", "create_tailored_resume", "triage_job"} <= (
        {name for name, notes in writes.items() if notes.destructive_hint is False})


async def test_only_tools_that_reach_the_web_are_open_world(server):
    listed = await tools(server)

    assert {name for name, tool in listed.items() if tool.annotations.open_world_hint} == OPEN_WORLD
    assert all(tool.annotations.open_world_hint is False for name, tool in listed.items() if name not in OPEN_WORLD)
