import pytest

from resume_fixture import fictitious_resume
from vagas.db import connect
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore

JOB = (
    "We are hiring a Data Scientist. Requirements: Python, SQL and Spark. "
    "Experience with AWS, Terraform and Kafka is a plus. Knowledge of C++ or OR-Tools/SCIP."
)


@pytest.fixture
def store(db_path, tmp_path):
    conn = connect(db_path)
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    resume = fictitious_resume()
    resume["skills"].append({"id": "skills-optimization", "label": "Optimization", "terms": ["OR-Tools/SCIP"]})
    s.save_master_draft(resume)
    s.approve_master()
    yield s
    conn.close()


def test_matched_and_missing_terms_with_score(store):
    result = store.score_job_match(JOB)

    assert result["matched"] == ["Data", "Scientist", "Python", "SQL", "AWS", "Terraform", "C++", "OR-Tools", "SCIP"]
    assert result["missing"] == ["Spark", "Kafka"]
    assert result["score"] == 82
    assert result["note"] is None


def test_repeated_terms_count_once_regardless_of_case(store):
    result = store.score_job_match("Strong Python skills. Python and PYTHON daily, plus Spark and Spark.")

    assert result["matched"] == ["Python"]
    assert result["missing"] == ["Spark"]
    assert result["score"] == 50


@pytest.mark.parametrize("description, score", [
    ("Must know Python, SQL and C#.", 100),
    ("Must know Rust, Go and Elixir.", 0),
])
def test_score_bounds(store, description, score):
    assert store.score_job_match(description)["score"] == score


def test_description_without_technical_terms_has_no_score(store):
    result = store.score_job_match("we are a friendly team looking for curious people.")

    assert (result["score"], result["matched"], result["missing"]) == (None, [], [])
    assert "termos técnicos" in result["note"]


def test_terms_from_any_part_of_the_master_count(store):
    result = store.score_job_match("Experience with Qdrant, Kubernetes, LinkedIn Learning certificates and English.")

    assert result["missing"] == []


def test_blank_description_is_rejected(store):
    with pytest.raises(VagasError, match="description"):
        store.score_job_match("   ")


def test_requires_approved_master(db_path, tmp_path):
    conn = connect(db_path)
    empty = ResumeStore(conn, tmp_path / "outro.yaml")

    with pytest.raises(VagasError, match="approve_master"):
        empty.score_job_match(JOB)


def test_list_markers_and_single_letters_are_not_terms(store):
    description = "Responsibilities:\n- Build pipelines in Python.\n• Develop dashboards.\n1. Nice to have: A/B Testing and Spark."

    result = store.score_job_match(description)

    assert result["matched"] == ["Python"]
    assert result["missing"] == ["Testing", "Spark"]
