"""Currículo fictício com a mesma forma do real: parágrafos longos, várias funções na mesma empresa."""

import copy


def fictitious_resume() -> dict:
    return copy.deepcopy(_RESUME)


_RESUME = {
    "basics": {
        "name": "Fulana de Tal",
        "headline": "Data Scientist | Machine Learning Engineer",
        "email": "fulana@example.com",
        "phone": "+55 (00) 00000-0000",
        "location": "Cidade, Brasil",
        "links": ["linkedin.com/in/fulana", "github.com/fulana"],
    },
    "education": [
        {
            "id": "edu-uni-phd",
            "institution": "Universidade Exemplo",
            "degree": "Ph.D.",
            "field": "Artificial Intelligence",
            "start": "Aug 2025",
            "end": "Present",
        },
    ],
    "experience": [
        {
            "id": "exp-acme-tech-lead",
            "company": "Acme Analytics",
            "context": "Funded AI Research Project",
            "title": "AI Engineering Technical Coordinator",
            "location": "Remote",
            "start": "May 2024",
            "end": "Sep 2025",
            "paragraphs": [
                {
                    "id": "exp-acme-tech-lead-p1",
                    "text": "Coordinated a conversational assistant built with FastAPI, LangChain and Qdrant, "
                            "reducing answer latency by 30% for 2M monthly requests.",
                },
                {
                    "id": "exp-acme-tech-lead-p2",
                    "text": "Ran the platform on AWS (S3, Lambda) and Kubernetes/K3s with Terraform.",
                },
            ],
        },
        {
            "id": "exp-acme-analyst",
            "company": "Acme Analytics",
            "title": "Quantitative Analyst",
            "location": "Remote",
            "start": "Feb 2024",
            "end": "Sep 2025",
            "paragraphs": [
                {"id": "exp-acme-analyst-p1", "text": "Maintained ETL pipelines in Python and SQL."},
            ],
        },
    ],
    "skills": [
        {"id": "skills-languages", "label": "Programming Languages", "terms": ["Python", "SQL", "C++", "C#"]},
    ],
    "certifications": [
        {
            "id": "cert-genai",
            "label": "Generative AI & LLMs",
            "items": [
                {"id": "cert-genai-graphrag", "name": "GraphRAG Essential Training",
                 "provider": "LinkedIn Learning", "year": 2026},
            ],
        },
    ],
    "languages": [
        {"name": "English", "level": "Upper-intermediate (B2)", "note": "Certification"},
        {"name": "Portuguese", "level": "Native"},
    ],
}
