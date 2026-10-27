import copy

import pypdf
import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_extract import review_draft
from vagas.resume_render import render_resume
from vagas.resume_repo import ResumeStore

VOLUNTEERING = {
    "id": "vol-codeclub",
    "organization": "Code Club Brasil",
    "role": "Volunteer Instructor",
    "location": "São Carlos, Brazil",
    "start": "Mar 2021",
    "end": "Dec 2022",
    "paragraphs": [{"id": "vol-codeclub-p1",
                    "text": "Taught Python to 40 high school students in weekly workshops."}],
}
CERT_LINK = "https://www.credly.com/badges/abc123"


def with_volunteering():
    resume = fictitious_resume()
    resume["volunteering"] = [copy.deepcopy(VOLUNTEERING)]
    resume["certifications"][0]["items"][0]["link"] = CERT_LINK
    return resume


@pytest.fixture
def store(db_path, tmp_path):
    conn = connect(db_path)
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    s.save_master_draft(with_volunteering())
    s.approve_master()
    yield s
    conn.close()


def pdf_text(path):
    return " ".join(" ".join(p.extract_text() for p in pypdf.PdfReader(path).pages).split())


def pdf_links(path):
    return {
        annot.get_object()["/A"].get("/URI")
        for page in pypdf.PdfReader(path).pages
        for annot in page.get("/Annots", [])
        if annot.get_object().get("/A")
    }


def test_master_keeps_volunteering_and_certification_link(store):
    master = store.get_master_resume()["resume"]

    assert master["volunteering"] == [VOLUNTEERING]
    assert master["certifications"][0]["items"][0]["link"] == CERT_LINK


def test_volunteering_ids_are_unique_with_the_rest_of_the_document(tmp_path, db_path):
    resume = with_volunteering()
    resume["volunteering"][0]["paragraphs"][0]["id"] = "exp-acme-analyst-p1"
    conn = connect(db_path)

    with pytest.raises(VagasError, match="exp-acme-analyst-p1"):
        ResumeStore(conn, tmp_path / "x.yaml").save_master_draft(resume)


def test_volunteering_without_description_is_allowed(tmp_path, db_path):
    resume = with_volunteering()
    resume["volunteering"][0]["paragraphs"] = []
    conn = connect(db_path)

    assert ResumeStore(conn, tmp_path / "x.yaml").save_master_draft(resume)["path"]


def test_master_pdf_renders_volunteering_and_certification_link(tmp_path):
    path = render_resume(with_volunteering(), tmp_path / "out")["path"]

    text = pdf_text(path)
    assert "Volunteering" in text
    for value in ("Code Club Brasil", "Volunteer Instructor", "São Carlos, Brazil", "Mar 2021", "Dec 2022",
                  "Taught Python to 40 high school students in weekly workshops."):
        assert value in text
    assert CERT_LINK in pdf_links(path)


def test_tailored_resume_can_select_and_rewrite_volunteering(store, tmp_path):
    selection = {"label": "Escola", "sections": [{"section": "volunteering", "items": [
        {"id": "vol-codeclub", "paragraphs": [
            {"id": "vol-codeclub-p1", "bullets": ["Taught Python to 40 students every week"]}]}]}]}

    result = store.create_tailored_resume(selection, tmp_path / "out")

    text = pdf_text(result["path"])
    assert "Volunteering" in text and "Taught Python to 40 students every week" in text
    assert "Experience" not in text


@pytest.mark.parametrize("pick, expected", [
    ({"id": "vol-codeclub", "paragraphs": [{"id": "vol-codeclub-p1", "bullets": ["Taught Python to 400 students"]}]},
     ["vol-codeclub-p1", "400"]),
    ({"id": "vol-codeclub", "paragraphs": [{"id": "vol-codeclub-p1", "bullets": ["Taught Rust to students"]}]},
     ["vol-codeclub-p1", "Rust"]),
    ({"id": "vol-codeclub", "paragraphs": [{"id": "exp-acme-analyst-p1"}]}, ["exp-acme-analyst-p1", "vol-codeclub"]),
    ({"id": "vol-codeclub", "role": "Director"}, ["role"]),
])
def test_volunteering_selection_is_validated(store, tmp_path, pick, expected):
    selection = {"sections": [{"section": "volunteering", "items": [pick]}]}

    with pytest.raises(VagasError) as error:
        store.create_tailored_resume(selection, tmp_path / "out")

    assert all(fragment in str(error.value) for fragment in expected), str(error.value)


def test_review_checks_volunteering_fields():
    reference = "Code Club Brasil Volunteer Instructor Mar 2021 Dec 2022 Taught Python to 40 high school students"
    draft = {"basics": {"name": "Code Club"}, "volunteering": [{
        **VOLUNTEERING, "role": "Volunteer Director",
        "paragraphs": [{"id": "vol-codeclub-p1", "text": "Taught Python to 400 students with Kafka."}],
    }]}

    review = {(item["where"], item["value"]) for item in review_draft(draft, reference)}

    assert review == {
        ("vol-codeclub.role", "Volunteer Director"),
        ("vol-codeclub.location", "São Carlos, Brazil"),
        ("vol-codeclub-p1", "400"),
        ("vol-codeclub-p1", "Kafka"),
    }


def test_review_checks_certification_link():
    draft = with_volunteering()

    review = review_draft({"basics": {"name": "x"}, "certifications": draft["certifications"]}, "x GraphRAG Essential "
                          "Training LinkedIn Learning 2026 Generative AI & LLMs")

    assert {(i["where"], i["value"]) for i in review} == {("cert-genai-graphrag.link", CERT_LINK)}
