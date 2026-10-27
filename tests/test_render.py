import io

import pypdf
import pytest

from resume_fixture import fictitious_resume
from vagas.repo import VagasError
from vagas.resume_render import render_resume


def pdf_text(path):
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(path).pages)


def flat(text):
    return " ".join(text.split())


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "Curriculos"


def test_renders_pdf_into_output_dir_with_professional_name(out_dir):
    result = render_resume(fictitious_resume(), out_dir, label="Nubank")

    assert result["path"] == str(out_dir / "Fulana_Tal_Resume_Nubank.pdf")
    assert result["pages"] == 1
    assert result["warnings"] == []
    assert (out_dir / "Fulana_Tal_Resume_Nubank.pdf").read_bytes().startswith(b"%PDF")


def test_pdf_contains_the_resume_content(out_dir):
    resume = fictitious_resume()

    text = flat(pdf_text(render_resume(resume, out_dir)["path"]))

    assert "Fulana de Tal" in text
    assert "Data Scientist | Machine Learning Engineer" in text
    for job in resume["experience"]:
        assert job["company"] in text
        assert job["title"] in text
        assert job["start"] in text
        for paragraph in job["paragraphs"]:
            assert paragraph["text"] in text
    assert "Universidade Exemplo" in text
    assert "GraphRAG Essential Training" in text
    assert "Upper-intermediate (B2)" in text


def test_special_characters_survive(out_dir):
    resume = fictitious_resume()
    resume["experience"][1]["paragraphs"][0]["text"] = (
        "Built R&D tooling in C++ and C# for São Carlos | São Paulo, cutting costs by 100% #1 *really* $5_000."
    )

    text = flat(pdf_text(render_resume(resume, out_dir)["path"]))

    assert "Built R&D tooling in C++ and C# for São Carlos | São Paulo, cutting costs by 100% #1 *really* $5_000." in text


def test_words_are_not_hyphenated_nor_ligated(out_dir):
    resume = fictitious_resume()
    resume["experience"][1]["paragraphs"][0]["text"] = " ".join(["internationalization efficiency"] * 30)

    text = pdf_text(render_resume(resume, out_dir)["path"])

    assert "-\n" not in text
    assert "ﬁ" not in text and "ﬀ" not in text
    assert text.count("efficiency") == 30


def test_existing_file_is_not_overwritten(out_dir):
    first = render_resume(fictitious_resume(), out_dir, label="Nubank")
    second = render_resume(fictitious_resume(), out_dir, label="Nubank")
    third = render_resume(fictitious_resume(), out_dir, label="Nubank")

    assert [first["path"], second["path"], third["path"]] == [
        str(out_dir / f"Fulana_Tal_Resume_Nubank{suffix}.pdf") for suffix in ("", "_2", "_3")
    ]


def test_label_is_sanitized_for_file_names(out_dir):
    result = render_resume(fictitious_resume(), out_dir, label="Itaú Unibanco S.A. / Dados")

    assert result["path"] == str(out_dir / "Fulana_Tal_Resume_Itau_Unibanco_S_A_Dados.pdf")


def test_more_than_two_pages_is_a_warning(out_dir):
    resume = fictitious_resume()
    long_text = resume["experience"][0]["paragraphs"][0]["text"]
    resume["experience"][0]["paragraphs"] = [
        {"id": f"exp-acme-tech-lead-p{i}", "text": long_text * 4} for i in range(1, 30)
    ]

    result = render_resume(resume, out_dir)

    assert result["pages"] > 2
    assert any("páginas" in warning for warning in result["warnings"])


def test_missing_output_dir_is_a_readable_error():
    with pytest.raises(VagasError, match="VAGAS_RESUME_OUT"):
        render_resume(fictitious_resume(), None)


def test_minimal_resume_renders(out_dir):
    result = render_resume({"basics": {"name": "Fulana"}}, out_dir)

    assert result["pages"] == 1
    assert "Fulana" in pdf_text(result["path"])
