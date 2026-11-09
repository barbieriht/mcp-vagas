"""Práticas de recrutadores de tecnologia: tópicos de resultado, sem clichês, até 2 páginas, foco pelo cargo e
skills com comprovação."""

import itertools

import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_render import render_resume
from vagas.resume_suggest import suggest_selection
from vagas.resume_tailor import TailoredSelection, resolve
from vagas.resume_repo import ResumeStore

P1, P2 = "exp-acme-tech-lead-p1", "exp-acme-tech-lead-p2"


def bullets(*texts, pid=P1):
    return {"section": "experience", "items": [{"id": "exp-acme-tech-lead", "paragraphs": [
        {"id": pid, "bullets": list(texts)}]}]}


@pytest.mark.parametrize("selection, fragment", [
    ({"sections": [bullets("Responsible for a conversational assistant with FastAPI, LangChain and Qdrant.")]},
     "Responsible for"),
    ({"sections": [bullets("Worked on a conversational assistant with FastAPI and LangChain.")]}, "Worked on"),
    ({"sections": [bullets("Helped with a conversational assistant built with FastAPI.")]}, "Helped with"),
    ({"summary": "Passionate engineer building conversational assistants with FastAPI.",
      "sections": [bullets("Coordinated a conversational assistant built with FastAPI.")]}, "passionate"),
    ({"headline": "Results-driven Tech Lead", "sections": [bullets("Coordinated an assistant with FastAPI.")]},
     "results-driven"),
])
def test_generic_openers_and_buzzwords_are_rejected(selection, fragment):
    with pytest.raises(VagasError) as error:
        resolve(fictitious_resume(), TailoredSelection.model_validate(selection))

    assert fragment.lower() in str(error.value).lower()


def test_action_bullets_from_the_master_are_accepted():
    resolve(fictitious_resume(), TailoredSelection.model_validate({"sections": [
        bullets("Coordinated a conversational assistant built with FastAPI, LangChain and Qdrant.")]}))


@pytest.fixture
def store(db_path, tmp_path):
    ticks = itertools.count()
    conn = connect(db_path)
    resume = fictitious_resume()
    long_text = resume["experience"][0]["paragraphs"][0]["text"]
    resume["experience"][0]["paragraphs"] += [
        {"id": f"exp-acme-tech-lead-p{i}", "text": long_text * 4} for i in range(3, 30)]
    s = ResumeStore(conn, tmp_path / "curriculo.yaml", now=lambda: f"2026-10-27T12:00:{next(ticks):02d}+00:00")
    s.save_master_draft(resume)
    s.approve_master()
    yield s
    conn.close()


def test_tailored_resume_over_two_pages_is_rejected_without_writing_a_file(store, tmp_path):
    out = tmp_path / "Curriculos"

    with pytest.raises(VagasError, match="páginas"):
        store.create_tailored_resume({"label": "X", "sections": [{"section": "experience"}]}, out)

    assert not out.exists() or list(out.iterdir()) == []
    assert store.list_resumes() == []


def test_master_render_still_only_warns_about_pages(tmp_path):
    resume = fictitious_resume()
    long_text = resume["experience"][0]["paragraphs"][0]["text"]
    resume["experience"][0]["paragraphs"] = [{"id": f"exp-acme-tech-lead-p{i}", "text": long_text * 4}
                                             for i in range(1, 30)]

    assert render_resume(resume, tmp_path / "out")["warnings"]


def master():
    resume = fictitious_resume()
    resume["experience"][0]["paragraphs"].append(
        {"id": "exp-acme-tech-lead-p3", "text": "Ran statistical analysis and A/B experiments for the product team."})
    return resume


def chosen_paragraphs(selection):
    experience = next(s for s in selection["sections"] if s["section"] == "experience")
    return [p["id"] for p in experience["items"][0]["paragraphs"]]


def test_engineering_roles_bring_production_paragraphs_and_science_roles_analysis():
    terms = ["LangChain"]  # só o p1 cita

    assert chosen_paragraphs(suggest_selection(master(), terms, None)["selection"]) == [P1]
    assert chosen_paragraphs(suggest_selection(master(), terms, None, role_key="ml_engineer")["selection"]) == [P1, P2]
    assert chosen_paragraphs(suggest_selection(master(), terms, None, role_key="data_scientist")["selection"]) == [
        P1, "exp-acme-tech-lead-p3"]


def test_suggested_skills_keep_job_terms_and_those_backed_by_experience():
    selection = suggest_selection(fictitious_resume(), ["Python"], None)["selection"]

    skills = next(s for s in selection["sections"] if s["section"] == "skills")["items"]
    group = next(g for g in skills if g["id"] == "skills-languages")
    assert group["terms"] == ["Python", "SQL"]  # C++ e C# não aparecem em nenhuma experiência
