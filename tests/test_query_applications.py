"""query_applications: filtros estruturados (E), sem SQL do chamador, linhas enxutas e paginadas."""

import pytest
from mcp import Client

from vagas.repo import VagasError

pytestmark = pytest.mark.anyio


def add(repo, role="Cientista de Dados", company="Acme", status="a_aplicar", **extra):
    if status == "descartada":
        extra.setdefault("discard_reason", "x")
    if status == "pendente_usuario":
        extra.setdefault("pending", "CPF")
    return repo.add_application(company=company, role=role, source="gupy", status=status, **extra)["application"]


def ids(result):
    return sorted(row["id"] for row in result["rows"])


def test_without_filters_returns_every_application_with_the_default_fields(repo):
    a = add(repo, url="https://acme.gupy.io/jobs/1", seniority="pleno", work_mode="remoto", match_score=70)

    result = repo.query_applications({})

    assert result["count"] == 1 and "next_offset" not in result
    assert result["rows"] == [{"id": a["id"], "company": "Acme", "role": "Cientista de Dados", "seniority": "pleno",
                               "work_mode": "remoto", "match_score": 70, "status": "a_aplicar",
                               "url": "https://acme.gupy.io/jobs/1"}]


def test_status_accepts_one_or_a_list(repo):
    open_ = add(repo)
    discarded = add(repo, status="descartada")
    applied = add(repo, status="aplicada")

    assert ids(repo.query_applications({"status": "a_aplicar"})) == [open_["id"]]
    assert ids(repo.query_applications({"status": ["a_aplicar", "aplicada"]})) == [open_["id"], applied["id"]]
    assert discarded["id"] not in ids(repo.query_applications({"status": ["a_aplicar"]}))


def test_seniority_list_and_missing_flag(repo):
    intern = add(repo, seniority="estagio")
    senior = add(repo, seniority="senior")
    unknown = add(repo)

    assert ids(repo.query_applications({"seniority": ["estagio"]})) == [intern["id"]]
    assert ids(repo.query_applications({"seniority_missing": True})) == [unknown["id"]]
    assert ids(repo.query_applications({"seniority": ["estagio"], "seniority_missing": True})) == [
        intern["id"], unknown["id"]]
    assert ids(repo.query_applications({"seniority_missing": False})) == [intern["id"], senior["id"]]


def test_work_mode_list_and_missing_flag(repo):
    remote = add(repo, work_mode="remoto")
    hybrid = add(repo, work_mode="hibrido")
    unknown = add(repo)

    assert ids(repo.query_applications({"work_mode": ["remoto", "hibrido"]})) == [remote["id"], hybrid["id"]]
    assert ids(repo.query_applications({"work_mode_missing": True})) == [unknown["id"]]


def test_location_substrings_ignore_case_and_accents(repo):
    sp = add(repo, location="São Paulo, SP, Brasil")
    campinas = add(repo, location="Campinas, São Paulo")
    nowhere = add(repo)

    assert ids(repo.query_applications({"location_any": ["SAO PAULO"]})) == [sp["id"], campinas["id"]]
    assert ids(repo.query_applications({"location_any": ["campinas"]})) == [campinas["id"]]
    assert ids(repo.query_applications({"location_none": ["Campínas"]})) == [sp["id"], nowhere["id"]]


def test_state_codes_or_names_resolve_like_the_triage(repo):
    sp = add(repo, location="Barueri, São Paulo, Brazil")
    rj = add(repo, location="Rio de Janeiro, RJ")
    remote = add(repo, location="Brasil")

    assert ids(repo.query_applications({"state_any": ["sp"]})) == [sp["id"]]
    assert ids(repo.query_applications({"state_any": ["São Paulo", "Rio de Janeiro"]})) == [sp["id"], rj["id"]]
    assert ids(repo.query_applications({"state_none": ["SP"]})) == [rj["id"], remote["id"]]


def test_unknown_state_is_a_clear_error(repo):
    with pytest.raises(VagasError, match=r"state_any.*Atlântida.*sigla"):
        repo.query_applications({"state_any": ["Atlântida"]})


def test_role_substrings_ignore_case_and_accents(repo):
    ds = add(repo, role="Cientista de Dados Sênior")
    intern = add(repo, role="Data Scientist Intern")
    add(repo, role="Engenheiro de Dados")

    assert ids(repo.query_applications({"role_any": ["cientista", "SCIENTIST"]})) == [ds["id"], intern["id"]]
    assert ids(repo.query_applications({"role_any": ["senior"]})) == [ds["id"]]


def test_role_none_accepts_a_regex_between_slashes(repo):
    add(repo, role="Data Scientist Intern")
    add(repo, role="Estagiário em Ciência de Dados")
    kept = add(repo, role="Internal Tools Data Scientist")

    result = repo.query_applications({"role_none": [r"/\b(intern|estagi\w*)\b/"]})

    assert ids(result) == [kept["id"]]


def test_invalid_regex_is_a_clear_error(repo):
    with pytest.raises(VagasError, match=r"role_any.*express"):
        repo.query_applications({"role_any": ["/(unclosed/"]})


def test_company_compares_the_normalized_name_by_whole_words(repo):
    itau = add(repo, company="Itaú Unibanco S.A.")
    cielo = add(repo, company="Cielo")

    assert ids(repo.query_applications({"company_any": ["ITAU"]})) == [itau["id"]]
    assert ids(repo.query_applications({"company_any": ["itau unibanco sa"]})) == [itau["id"]]
    assert ids(repo.query_applications({"company_any": ["ci"]})) == []
    assert ids(repo.query_applications({"company_none": ["Itaú"]})) == [cielo["id"]]


def test_match_score_range_and_missing_flag(repo):
    low = add(repo, match_score=20)
    high = add(repo, match_score=90)
    unscored = add(repo)

    assert ids(repo.query_applications({"match_score_min": 50})) == [high["id"]]
    assert ids(repo.query_applications({"match_score_max": 50})) == [low["id"]]
    assert ids(repo.query_applications({"match_score_max": 50, "match_score_missing": True})) == [
        low["id"], unscored["id"]]
    assert ids(repo.query_applications({"match_score_missing": True})) == [unscored["id"]]


def test_needs_any_and_none(repo):
    no_mode = add(repo)
    repo.set_needs(no_mode["id"], [{"kind": "modalidade", "detail": "sem modalidade"}])
    no_role = add(repo, work_mode="remoto")
    repo.set_needs(no_role["id"], [{"kind": "cargo", "detail": "?"}, {"kind": "aderencia", "detail": "?"}])
    clean = add(repo, work_mode="remoto")

    assert ids(repo.query_applications({"needs_any": ["modalidade", "cargo"]})) == [no_mode["id"], no_role["id"]]
    assert ids(repo.query_applications({"needs_none": ["cargo"]})) == [no_mode["id"], clean["id"]]
    rows = repo.query_applications({"needs_any": ["cargo"]}, fields=["id", "needs"])["rows"]
    assert rows == [{"id": no_role["id"], "needs": ["cargo", "aderencia"]}]


def test_search_ids_and_creation_dates(repo):
    search = repo.conn.execute(
        "INSERT INTO job_searches (query, query_norm, source, results_count, searched_at) "
        "VALUES ('ds', 'ds', 'gupy', 1, '2026-11-01T00:00:00+00:00')").lastrowid
    repo.conn.commit()
    times = iter(["2026-10-01T10:00:00+00:00", "2026-11-05T23:00:00+00:00", "2026-11-06T00:00:00+00:00"])
    repo.now = lambda: next(times)
    old, from_search, newer = add(repo), add(repo, search_id=search), add(repo)

    assert ids(repo.query_applications({"search_id": search})) == [from_search["id"]]
    assert ids(repo.query_applications({"created_since": "2026-11-01"})) == [from_search["id"], newer["id"]]
    assert ids(repo.query_applications({"created_until": "2026-11-05"})) == [old["id"], from_search["id"]]
    assert ids(repo.query_applications({"ids": [old["id"], newer["id"]]})) == [old["id"], newer["id"]]


def test_filters_combine_with_and(repo):
    target = add(repo, role="Data Scientist Intern", seniority="estagio", location="São Paulo, SP")
    add(repo, role="Data Scientist Intern", seniority="estagio", status="descartada")
    add(repo, role="Data Scientist", seniority="pleno", location="São Paulo, SP")

    result = repo.query_applications({"status": "a_aplicar", "seniority": ["estagio"], "state_any": ["SP"],
                                      "role_any": ["intern"]})

    assert ids(result) == [target["id"]]


def test_fields_order_and_pagination(repo):
    first = add(repo, company="Beta", match_score=10)
    second = add(repo, company="Alfa", match_score=90)
    third = add(repo, company="Gama")

    by_score = repo.query_applications({}, fields=["company", "match_score"], order_by="-match_score", limit=2)

    assert by_score["rows"] == [{"id": second["id"], "company": "Alfa", "match_score": 90},
                                {"id": first["id"], "company": "Beta", "match_score": 10}]
    assert by_score["count"] == 3 and by_score["next_offset"] == 2
    rest = repo.query_applications({}, fields=["company"], order_by="-match_score", limit=2, offset=2)
    assert rest["rows"] == [{"id": third["id"], "company": "Gama"}] and "next_offset" not in rest
    by_company = repo.query_applications({}, fields=["company"], order_by="company")
    assert [r["company"] for r in by_company["rows"]] == ["Alfa", "Beta", "Gama"]


def test_unknown_filter_key_is_rejected(repo):
    with pytest.raises(VagasError, match="sql"):
        repo.query_applications({"sql": "1=1"})


async def test_tool_returns_compact_rows_without_the_job_text(server):
    async with Client(server) as client:
        await client.call_tool("add_application", {
            "company": "Acme", "role": "Data Scientist Intern", "source": "gupy", "status": "a_aplicar",
            "description": "Texto longo da vaga.", "seniority": "estagio"})
        result = await client.call_tool("query_applications", {"filter": {"seniority": ["estagio"]},
                                                                "fields": ["role", "status", "description"]})
        ok = await client.call_tool("query_applications", {"filter": {"seniority": ["estagio"]},
                                                            "fields": ["role", "status"]})
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert result.is_error  # description não está entre os campos
    assert ok.structured_content["rows"] == [{"id": 1, "role": "Data Scientist Intern", "status": "a_aplicar"}]
    assert tools["query_applications"].annotations.read_only_hint is True
