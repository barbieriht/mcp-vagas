"""needs da triagem gravados na candidatura: consultáveis, limpos quando resolvidos, recuperados das buscas em lote."""

import json

import pytest

from resume_fixture import fictitious_resume
from test_triage import CRITERIA, POLICY, Fetcher, gupy
from vagas.db import connect
from vagas.repo import Repo
from vagas.resume_repo import ResumeStore
from vagas.salary import SalaryStore
from vagas.triage import Triage


def add(repo, **extra):
    return repo.add_application(company="Acme", role="Cientista de Dados", source="gupy", status="a_aplicar",
                                **extra)["application"]


def kinds(repo, app_id):
    return [n["kind"] for n in repo.get(app_id).get("needs") or []]


@pytest.fixture
def triage(db_path, tmp_path, monkeypatch):
    monkeypatch.delenv("VAGAS_SALARY_TTL_DAYS", raising=False)
    conn = connect(db_path)
    store = ResumeStore(conn, tmp_path / "curriculo.yaml")
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    (tmp_path / "criterios-triagem.md").write_text(CRITERIA, encoding="utf-8")
    (tmp_path / "politica-salarial.md").write_text(POLICY, encoding="utf-8")
    fetcher = Fetcher()
    yield Triage(conn, fetcher=fetcher, criteria_path=tmp_path / "criterios-triagem.md",
                 policy_path=tmp_path / "politica-salarial.md", draft_path=tmp_path / "curriculo.yaml"), fetcher
    conn.close()


def test_triage_saves_its_needs_on_the_application(triage):
    t, fetcher = triage
    url = fetcher.add(gupy(1, name="Cientista de Dados Pleno", mode="unknown"))

    result = t.triage_job(url)

    assert result["decision"] == "a_aplicar"
    saved = t.repo.get(result["application"]["id"])["needs"]
    assert [n["kind"] for n in saved] == [n["kind"] for n in result["needs"]]
    assert "modalidade" in [n["kind"] for n in saved]
    assert all(set(n) == {"kind", "detail"} for n in saved)


def test_setting_the_work_mode_resolves_modalidade(repo):
    app = add(repo)
    repo.set_needs(app["id"], [{"kind": "modalidade", "detail": "?"}, {"kind": "afirmativa", "detail": "?"}])

    repo.update_application(app["id"], work_mode="hibrido")

    assert kinds(repo, app["id"]) == ["afirmativa"]


def test_remote_resolves_local_and_seniority_resolves_senioridade(repo):
    app = add(repo, work_mode="hibrido")
    repo.set_needs(app["id"], [{"kind": "local", "detail": "?"}, {"kind": "senioridade", "detail": "?"}])

    repo.set_seniority(app["id"], "pleno", "3 anos pedidos")
    assert kinds(repo, app["id"]) == ["local"]
    repo.update_application(app["id"], work_mode="remoto")
    assert repo.get(app["id"]).get("needs") is None


def test_a_salary_evaluation_resolves_salary_and_role_needs(db_path, tmp_path):
    conn = connect(db_path)
    repo = Repo(conn)
    (tmp_path / "politica-salarial.md").write_text(POLICY, encoding="utf-8")
    app = add(repo, work_mode="remoto", seniority="pleno")
    repo.set_needs(app["id"], [{"kind": "cargo", "detail": "?"}, {"kind": "salario", "detail": "?"},
                               {"kind": "pesquisa_salarial", "detail": "?"}])
    salaries = SalaryStore(conn, policy_path=tmp_path / "politica-salarial.md")
    salaries.save_salary_estimate("data_scientist", "pleno", "BRL", points=[
        {"source": "glassdoor", "contract": "clt", "period": "mes", "avg_value": 12000}])

    result = salaries.evaluate_salary("data_scientist", "pleno", "BRL", "clt", application_id=app["id"])

    assert result["decision"] == "aplicar"
    remaining = kinds(repo, app["id"])
    assert "cargo" not in remaining and "salario" not in remaining
    assert ("pesquisa_salarial" in remaining) == result["needs_research"]
    conn.close()


def test_rescore_resolves_aderencia_when_a_score_appears(repo):
    app = add(repo)
    repo.set_needs(app["id"], [{"kind": "aderencia", "detail": "sem termos"}])

    repo.set_match(app["id"], 70, {"matched": ["Python"], "missing": []})

    assert repo.get(app["id"]).get("needs") is None


def test_rescore_adds_aderencia_when_the_score_goes_away(repo):
    app = add(repo, match_score=100, match_terms={"matched": ["Excel"], "missing": []})

    repo.set_match(app["id"], None, {"matched": ["Excel"], "missing": []}, note="Poucos termos técnicos.")

    assert repo.get(app["id"])["needs"] == [{"kind": "aderencia", "detail": "Poucos termos técnicos."}]


def test_summaries_show_only_the_kinds(server):
    from vagas.tool_output import application_record, application_summary

    app = {"id": 1, "needs": [{"kind": "cargo", "detail": "texto longo"}]}

    assert application_summary(app)["needs"] == ["cargo"]
    assert application_record(app)["needs"] == ["cargo"]


def test_migration_backfills_kinds_from_batch_summaries(db_path):
    conn = connect(db_path)
    now = "2026-11-01T00:00:00+00:00"
    for i, mode in ((1, None), (2, "remoto"), (3, None)):
        conn.execute("INSERT INTO applications (id, company, company_norm, role, source, status, work_mode, "
                     "created_at, updated_at) VALUES (?, 'A', 'a', 'DS', 'gupy', 'a_aplicar', ?, ?, ?)",
                     (i, mode, now, now))
    summary = {"a_aplicar": [{"id": 1, "needs": ["modalidade", "cargo"]}, {"id": 2, "needs": ["modalidade"]},
                             {"id": 99, "needs": ["cargo"]}]}
    conn.execute("INSERT INTO search_runs (params, status, summary, started_at) VALUES ('{}', 'done', ?, ?)",
                 (json.dumps(summary), now))
    conn.execute("INSERT INTO search_runs (params, status, summary, started_at) VALUES ('{}', 'done', 'x', ?)",
                 (now,))
    conn.commit()
    conn.execute("ALTER TABLE applications DROP COLUMN needs")
    conn.execute("PRAGMA user_version = 17")
    conn.commit()
    conn.close()

    conn = connect(db_path)

    rows = {r["id"]: r["needs"] for r in conn.execute("SELECT id, needs FROM applications")}
    assert json.loads(rows[1]) == [{"kind": "modalidade"}, {"kind": "cargo"}]
    assert rows[2] is None  # modalidade já resolvida: a vaga tem work_mode
    assert rows[3] is None  # triada fora de uma busca em lote: sem como recuperar
    conn.close()
