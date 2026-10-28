import pytest

from vagas.linkedin_parse import month_year, parse_certifications, unwrap_link

SAFE = "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Ffreecodecamp%2Eorg%2Fcertification%2Ffulana%2Fml&urlhash=x"


def block(*lines, links=()):
    return {"lines": list(lines), "links": [{"text": t, "href": h} for t, h in links]}


BLOCKS = [
    block("Build AI Agents with LangGraph", "LinkedIn", "Issued Oct 2026", "Show credential", "Skills: Chatbots",
          links=[("", "https://www.linkedin.com/company/1337/"),
                 ("Show credential", "https://www.linkedin.com/learning/certificates/abc123/")]),
    block("LLMOps Masterclass 2026", "Manifold AI Learning", "Issued Sep 2026", "Credential ID UC-4450",
          "Show credential", "Skills: Python, +8 skills", "LLMOps Masterclass 2026",
          "Developed practical skills in Generative AI and LLMOps with FastAPI and Docker.",
          links=[("Show credential", "https://www.udemy.com/certificate/UC-4450/")]),
    block("Machine Learning with Python", "freeCodeCamp", "Issued Aug 2023", "Show credential",
          links=[("Show credential", SAFE)]),
    block("Digital Image Processing", "Great Learning", "Issued Nov 2023", "Show credential",
          "Skills: Computer Vision", "Fulana.pdf"),
    block("Curso sem data", "Alura"),
]


def test_parses_fields_of_each_certification():
    groups, warnings = parse_certifications(BLOCKS)

    items = {i["name"]: i for g in groups for i in g["items"]}
    assert items["Build AI Agents with LangGraph"] == {
        "id": "cert-build-ai-agents-with-langgraph", "name": "Build AI Agents with LangGraph",
        "provider": "LinkedIn", "issued": "2026-10", "link": "https://www.linkedin.com/learning/certificates/abc123/",
    }
    assert items["LLMOps Masterclass 2026"]["credential_id"] == "UC-4450"
    assert items["LLMOps Masterclass 2026"]["description"] == \
        "Developed practical skills in Generative AI and LLMOps with FastAPI and Docker."
    assert items["Machine Learning with Python"]["link"] == "https://freecodecamp.org/certification/fulana/ml"
    assert "description" not in items["Digital Image Processing"]
    assert items["Curso sem data"] == {"id": "cert-curso-sem-data", "name": "Curso sem data", "provider": "Alura"}
    assert warnings == []


def test_groups_by_provider_in_order_of_appearance():
    groups, _ = parse_certifications(BLOCKS)

    assert [(g["id"], g["label"], len(g["items"])) for g in groups] == [
        ("certs-linkedin", "LinkedIn", 1), ("certs-manifold-ai-learning", "Manifold AI Learning", 1),
        ("certs-freecodecamp", "freeCodeCamp", 1), ("certs-great-learning", "Great Learning", 1),
        ("certs-alura", "Alura", 1),
    ]


def test_same_name_gets_unique_ids():
    groups, _ = parse_certifications([block("Course", "A", "Issued Jan 2024"), block("Course", "B", "Issued Feb 2024")])

    assert [i["id"] for g in groups for i in g["items"]] == ["cert-course", "cert-course-2"]


def test_duplicate_credential_is_merged_keeping_oldest_with_warning():
    groups, warnings = parse_certifications([
        block("Course", "A", "Issued Mar 2025", "Credential ID X-1"),
        block("Course", "A", "Issued Jan 2025", "Credential ID X-1"),
    ])

    [item] = [i for g in groups for i in g["items"]]
    assert item["issued"] == "2025-01"
    assert any("X-1" in w and "LinkedIn" in w for w in warnings)


def test_unrecognized_block_is_a_warning():
    groups, warnings = parse_certifications([block()])

    assert groups == []
    assert warnings and "não reconhecido" in warnings[0]


@pytest.mark.parametrize("text, value", [
    ("Issued Oct 2026", "2026-10"), ("Issued Jan 2024 · Expires Jan 2027", "2024-01"),
    ("Mar 2019", "2019-03"), ("2019", "2019"), ("Emitido em out de 2026", None),
])
def test_month_year(text, value):
    assert month_year(text) == value


def test_unwrap_link():
    assert unwrap_link(SAFE) == "https://freecodecamp.org/certification/fulana/ml"
    assert unwrap_link("https://www.udemy.com/certificate/UC-1/") == "https://www.udemy.com/certificate/UC-1/"


def test_section_heading_block_is_skipped():
    groups, warnings = parse_certifications([block("Licenses & certifications"), block("Course", "A")])

    assert [i["name"] for g in groups for i in g["items"]] == ["Course"]
    assert warnings == []


def test_media_card_title_is_not_part_of_description():
    groups, _ = parse_certifications([block(
        "GraphRAG Essential Training", "LinkedIn", "Issued Aug 2026", "Graph Essential Training",
        "Learned the fundamentals of GraphRAG with Python and Neo4j.")])

    assert groups[0]["items"][0]["description"] == "Learned the fundamentals of GraphRAG with Python and Neo4j."
