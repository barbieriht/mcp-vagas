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

    assert result["matched"] == ["Python", "SQL", "AWS", "Terraform", "C++", "OR-Tools", "SCIP"]
    assert result["missing"] == ["Spark", "Kafka"]
    assert result["score"] == 78
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
    assert result["missing"] == ["Spark"]


LINKEDIN = (
    "A BairesDev® é um time apaixonado por inovação. Somos globais, somos GPTW. #VemSerBairesDev "
    "Description We are looking for a Senior Data Scientist in São Paulo. What You Bring: Python, SQL, "
    "Spark and PyTorch. Experience with Kafka, MLOps and LLM applications. Nosso Jeito: TODOS juntos. "
    "Benefícios: Gympass, Vale Refeição. Contrato CLT, modelo Híbrido em São Paulo."
)


def test_only_technical_terms_count(store):
    result = store.score_job_match(LINKEDIN, company="BairesDev", title="Senior Data Scientist",
                                   location="São Paulo, São Paulo, Brazil")

    assert result["matched"] == ["Python", "SQL"]
    assert result["missing"] == ["Spark", "PyTorch", "Kafka", "MLOps", "LLM"]
    assert result["score"] == 29


def test_company_and_title_words_are_ignored(store):
    result = store.score_job_match("Cientista de Dados na Leega. Buscamos TODOS com Python e Airflow.",
                                   company="Leega Consultoria", title="Cientista de Dados Sênior")

    assert (result["matched"], result["missing"]) == (["Python"], ["Airflow"])


def test_known_technologies_count_at_sentence_start(store):
    result = store.score_job_match("Docker é essencial. Snowflake também. Tableau é diferencial.")

    assert result["missing"] == ["Docker", "Snowflake", "Tableau"]


def test_noise_from_real_descriptions_is_ignored(store):
    description = ("Modelo híbrido 3x por semana, 24h de suporte. Ambiente LGBTQIA+ e PcD. Salário em USD. "
                   "Benefícios: TotalPass, Gympass. Metas e KPIs. Conhecimento em Statsmodels.Conhecimento em C# "
                   "e C++ e Spark.")

    result = store.score_job_match(description)

    assert result["missing"] == ["Statsmodels", "Spark"]
    assert "C++" in result["matched"] and "C#" in result["matched"]


@pytest.fixture
def ml_store(db_path, tmp_path):
    conn = connect(db_path)
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    resume = fictitious_resume()
    resume["skills"].append({"id": "skills-ml", "label": "Machine Learning", "terms": ["LightGBM", "AWS", "Qdrant"]})
    s.save_master_draft(resume)
    s.approve_master()
    yield s
    conn.close()


def test_missing_terms_point_to_related_ones_in_the_resume(ml_store):
    result = ml_store.score_job_match("Requisitos: Python, XGBoost, Azure, Pinecone, MLflow e Kafka.")

    assert result["missing"] == ["XGBoost", "Azure", "Pinecone", "MLflow", "Kafka"]
    assert result["related"] == {"XGBoost": ["LightGBM"], "Azure": ["AWS"], "Pinecone": ["Qdrant"]}
    assert result["score"] == 17  # relacionados não contam como presentes


def test_no_related_when_nothing_missing_or_no_description_terms(ml_store):
    assert ml_store.score_job_match("Python e LightGBM.")["related"] == {}
    assert ml_store.score_job_match("we are a friendly team.")["related"] == {}


@pytest.mark.anyio
async def test_related_is_documented_in_the_tool(server):
    from mcp import Client

    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert "related" in tools["score_job_match"].description and "related" in tools["triage_job"].description


def test_optional_terms_weigh_half_gupy_style(store):
    result = store.score_job_match("Requisitos: Python e SQL. Diferenciais: Kafka, Spark e Airflow. "
                                   "Benefícios: VR e Docker no dia a dia.")

    assert result["missing"] == ["Kafka", "Spark", "Airflow", "Docker"]
    assert result["optional"] == ["Kafka", "Spark", "Airflow"]
    assert result["score"] == 44  # 2 / (2 + 1,5 + 1)


def test_optional_terms_weigh_half_linkedin_style(store):
    result = store.score_job_match("What you bring • Python • SQL • Kafka Nice to have • Spark • Airflow "
                                   "Benefits • Health insurance")

    assert result["optional"] == ["Spark", "Airflow"]
    assert result["score"] == 50  # 2 / (2 + 1 + 0,5 + 0,5)


def test_term_also_required_is_not_optional(store):
    result = store.score_job_match("Requisitos: Kafka. Diferenciais: Kafka e Spark.")

    assert result["optional"] == ["Spark"]


def test_inline_desejavel_without_colon_is_not_a_section(store):
    result = store.score_job_match("Python e Kafka. Inglês desejável. Spark é usado no time.")

    assert result["optional"] == []
    assert result["score"] == 33


def test_short_family_names_are_matched_whole_not_by_letters(db_path, tmp_path):
    conn = connect(db_path)
    s = ResumeStore(conn, tmp_path / "curriculo.yaml")
    resume = fictitious_resume()
    resume["skills"].append({"id": "skills-letras", "label": "Letras", "terms": ["W", "B", "Power BI"]})
    s.save_master_draft(resume)
    s.approve_master()

    result = s.score_job_match("Requisitos: Python, MLflow e Tableau.")
    conn.close()

    assert result["related"] == {"Tableau": ["Power BI"]}  # sem "MLflow: W&B" vindo das letras soltas
