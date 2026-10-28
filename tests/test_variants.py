import pypdf
import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_extract import review_draft
from vagas.resume_render import render_resume
from vagas.resume_repo import ResumeStore


def enriched():
    resume = fictitious_resume()
    resume["basics"]["headline_variants"] = ["Data Scientist | PhD Candidate, AI (Universidade Exemplo)"]
    analyst = resume["experience"][1]
    analyst.update(location="São Paulo, Brazil", work_mode="remote", title_aliases=["Quant Analyst"])
    return resume


@pytest.fixture
def store(db_path, tmp_path):
    conn = connect(db_path)
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    s.save_master_draft(enriched())
    s.approve_master()
    yield s
    conn.close()


def pdf_text(path):
    return " ".join(" ".join(p.extract_text() for p in pypdf.PdfReader(path).pages).split())


def analyst(title=None):
    item = {"id": "exp-acme-analyst"}
    if title:
        item["title"] = title
    return {"sections": [{"section": "experience", "items": [item]}]}


def test_new_fields_are_kept(store):
    master = store.get_master_resume()["resume"]

    assert master["basics"]["headline_variants"] == ["Data Scientist | PhD Candidate, AI (Universidade Exemplo)"]
    assert master["experience"][1]["work_mode"] == "remote"
    assert master["experience"][1]["title_aliases"] == ["Quant Analyst"]


def test_invalid_work_mode_is_rejected(db_path, tmp_path):
    resume = enriched()
    resume["experience"][1]["work_mode"] = "home office"

    with pytest.raises(VagasError, match="work_mode"):
        ResumeStore(connect(db_path), tmp_path / "x.yaml").save_master_draft(resume)


def test_headline_from_a_variant_is_accepted(store, tmp_path):
    selection = {**analyst(), "headline": "Data Scientist | PhD Candidate, AI"}

    text = pdf_text(store.create_tailored_resume(selection, tmp_path / "out")["path"])

    assert "Data Scientist | PhD Candidate, AI" in text


def test_title_alias_can_be_chosen(store, tmp_path):
    result = store.create_tailored_resume(analyst("Quant Analyst"), tmp_path / "out")

    text = pdf_text(result["path"])
    assert "Quant Analyst" in text and "Quantitative Analyst" not in text
    assert store.get_resume(result["id"])["resolved"]["experience"][0]["title"] == "Quant Analyst"


def test_invented_title_is_rejected(store, tmp_path):
    with pytest.raises(VagasError, match="Head of Data"):
        store.create_tailored_resume(analyst("Head of Data"), tmp_path / "out")


def test_title_only_applies_to_experience(store, tmp_path):
    selection = {"sections": [{"section": "education", "items": [{"id": "edu-uni-phd", "title": "PhD"}]}]}

    with pytest.raises(VagasError, match="title"):
        store.create_tailored_resume(selection, tmp_path / "out")


def test_pdf_shows_location_and_work_mode(tmp_path):
    text = pdf_text(render_resume(enriched(), tmp_path / "out")["path"])

    assert "São Paulo, Brazil · Remote" in text


def test_review_checks_headline_variants_and_title_aliases():
    draft = {"basics": {"name": "Ana", "headline_variants": ["Invented Headline"]},
             "experience": [{"id": "exp-x", "company": "Ana", "title": "Ana", "start": "Ana",
                             "title_aliases": ["Chief Wizard"], "paragraphs": [{"id": "exp-x-p1", "text": "Ana"}]}]}

    review = {(i["where"], i["value"]) for i in review_draft(draft, "Ana")}

    assert review == {("basics.headline_variants", "Invented Headline"), ("exp-x.title_aliases", "Chief Wizard")}


def test_old_drafts_remain_valid(db_path, tmp_path):
    assert ResumeStore(connect(db_path), tmp_path / "x.yaml").save_master_draft(fictitious_resume())["path"]
