import os
from pathlib import Path

import pypdf
import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_extract import review_draft, wsl_path
from vagas.resume_render import render_resume
from vagas.resume_repo import ResumeStore


@pytest.fixture
def store(db_path, tmp_path):
    conn = connect(db_path)
    yield ResumeStore(conn, tmp_path / "curriculo.yaml")
    conn.close()


@pytest.fixture
def fictitious_pdf(tmp_path):
    return render_resume(fictitious_resume(), tmp_path / "pdf")["path"]


def where(review):
    return {(item["where"], item["value"]) for item in review}


def test_extract_returns_text_per_page(store, fictitious_pdf):
    result = store.extract_resume_text(fictitious_pdf)

    assert result["path"] == fictitious_pdf
    assert result["page_count"] == 1
    assert "Acme Analytics" in result["pages"][0]


def test_missing_file_is_a_readable_error(store, tmp_path):
    with pytest.raises(VagasError, match="não existe"):
        store.extract_resume_text(tmp_path / "nada.pdf")


def test_non_pdf_is_a_readable_error(store, tmp_path):
    fake = tmp_path / "x.pdf"
    fake.write_text("não sou pdf")

    with pytest.raises(VagasError, match="PDF"):
        store.extract_resume_text(fake)


def test_pdf_without_text_is_a_readable_error(store, tmp_path):
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    blank = tmp_path / "blank.pdf"
    with open(blank, "wb") as f:
        writer.write(f)

    with pytest.raises(VagasError, match="sem texto"):
        store.extract_resume_text(blank)


def test_windows_paths_are_accepted():
    assert wsl_path(r"C:\Users\Thiago\Downloads\cv.pdf") == Path("/mnt/c/Users/Thiago/Downloads/cv.pdf")
    assert wsl_path("/home/x/cv.pdf") == Path("/home/x/cv.pdf")


def test_save_without_reference_has_no_review(store):
    result = store.save_master_draft(fictitious_resume())

    assert result["review"] is None


def test_faithful_draft_has_empty_review(store, fictitious_pdf):
    store.extract_resume_text(fictitious_pdf)

    result = store.save_master_draft(fictitious_resume())

    assert result["review"] == []
    assert result["reference"] == fictitious_pdf


def test_invented_content_is_reported_with_item_id(store, fictitious_pdf):
    store.extract_resume_text(fictitious_pdf)
    resume = fictitious_resume()
    tech_lead = resume["experience"][0]
    tech_lead["paragraphs"][0]["text"] = tech_lead["paragraphs"][0]["text"].replace("30%", "45%")
    tech_lead["paragraphs"][1]["text"] += " Also used Kafka."
    tech_lead["start"] = "Jan 2023"
    resume["experience"][1]["title"] = "Head of Data"
    resume["basics"]["phone"] = "+55 (11) 91234-5678"

    review = store.save_master_draft(resume)["review"]

    assert where(review) == {
        ("exp-acme-tech-lead-p1", "45%"),
        ("exp-acme-tech-lead-p2", "Kafka"),
        ("exp-acme-tech-lead.start", "Jan 2023"),
        ("exp-acme-analyst.title", "Head of Data"),
        ("basics.phone", "+55 (11) 91234-5678"),
    }
    assert all(item["reason"] for item in review)


def test_review_tolerates_glued_words_hyphenation_ligatures_and_line_breaks():
    reference = (
        "Languages\n•EnglishUpper-intermediate (B2) Certification\n"
        "Built a robo-advisor with Kuber-\nnetes and LLM-\nbased agents, re\uFB01ning prompts.\n"
        "Newfoundland Capital\nManagement Feb 2022 – Feb 2024\nOR-Tools/SCIP"
    )
    draft = {
        "basics": {"name": "Fulana"},
        "experience": [{
            "id": "exp-x", "company": "Newfoundland Capital Management", "title": "Analyst",
            "start": "Feb 2022", "end": "Feb 2024",
            "paragraphs": [{"id": "exp-x-p1",
                            "text": "Built a robo-advisor with Kubernetes and LLM-based agents, refining prompts "
                                    "with OR-Tools/SCIP."}],
        }],
        "languages": [{"name": "English", "level": "Upper-intermediate (B2)", "note": "Certification"}],
    }

    review = review_draft(draft, reference)

    assert where(review) == {("basics.name", "Fulana"), ("exp-x.title", "Analyst")}


real_pdf = os.environ.get("VAGAS_TEST_RESUME_PDF")
needs_real_pdf = pytest.mark.skipif(
    not real_pdf or not Path(real_pdf).exists(),
    reason="defina VAGAS_TEST_RESUME_PDF com o caminho do currículo real para rodar",
)


@needs_real_pdf
def test_real_pdf_extracts_both_pages_and_known_anchors(store):
    result = store.extract_resume_text(real_pdf)

    # Sem espaços: o pdfTeX quebra títulos em versalete ("Educa tion"), como o relatório tolera.
    squashed = "".join(" ".join(result["pages"]).split())
    assert result["page_count"] == 2
    assert all(len(page) > 500 for page in result["pages"])
    for anchor in ("Qdrant", "OR-Tools/SCIP", "C++", "C#", "Experience", "Education"):
        assert anchor in squashed


@needs_real_pdf
def test_real_pdf_lines_produce_no_false_alerts(store):
    # Cada linha do próprio PDF usada como conteúdo do rascunho não pode gerar alerta.
    pages = store.extract_resume_text(real_pdf)["pages"]
    lines = [line.strip("• ") for page in pages for line in page.splitlines() if len(line.strip()) > 3]
    draft = {
        "basics": {"name": lines[0]},
        "experience": [{
            "id": f"exp-{i}", "company": line, "title": line, "start": line,
            "paragraphs": [{"id": f"exp-{i}-p1", "text": line}],
        } for i, line in enumerate(lines)],
    }

    assert review_draft(draft, "\n".join(pages)) == []


@needs_real_pdf
def test_real_pdf_is_never_inside_the_repository():
    repo = Path(__file__).resolve().parents[1]
    assert not Path(real_pdf).resolve().is_relative_to(repo)
    assert not any(repo.rglob(Path(real_pdf).name))
