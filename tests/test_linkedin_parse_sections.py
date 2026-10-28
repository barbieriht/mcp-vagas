from vagas.linkedin_parse import parse_education, parse_experience, parse_volunteering


def block(*lines, links=(), roles=None):
    b = {"lines": list(lines), "links": [{"text": t, "href": h} for t, h in links]}
    if roles is not None:
        b["roles"] = roles
    return b


GROUPED = block("Acme Analytics", "3 yrs 8 mos", "Remote", roles=[
    block("AI Technical Coordinator (Funded research project)", "Full-time", "May 2024 - Sep 2025 · 1 yr 5 mos",
          "Coordinated an assistant built with FastAPI and Qdrant.", "Ran it on AWS with Terraform.",
          "Skills: Python, +3 skills"),
    block("Quantitative Analyst", "Full-time", "Feb 2024 - Present · 1 yr 8 mos", "São Paulo, São Paulo, Brazil · Hybrid",
          "Maintained ETL pipelines in Python and SQL."),
])
SINGLE = block("Researcher", "CNPq", "Aug 2020 - Sep 2021 · 1 yr 2 mos",
               "Developed a multiplayer game in Unity (C#).", "Certificate of presentation - Fulana.pdf",
               "Unity, C# and +1 skill")


def test_grouped_roles_become_separate_items_with_company_from_header():
    items, extras, warnings = parse_experience([GROUPED, SINGLE])

    coordinator, analyst, researcher = items
    assert coordinator == {
        "id": "exp-acme-analytics-ai-technical-coordinator", "company": "Acme Analytics",
        "context": "Funded research project", "title": "AI Technical Coordinator", "work_mode": "remote",
        "start": "May 2024", "end": "Sep 2025",
        "paragraphs": [
            {"id": "exp-acme-analytics-ai-technical-coordinator-p1",
             "text": "Coordinated an assistant built with FastAPI and Qdrant."},
            {"id": "exp-acme-analytics-ai-technical-coordinator-p2", "text": "Ran it on AWS with Terraform."},
        ],
    }
    assert (analyst["location"], analyst["work_mode"], analyst["end"]) == ("São Paulo, São Paulo, Brazil", "hybrid", "Present")
    assert researcher["company"] == "CNPq" and researcher["title"] == "Researcher"
    assert [p["text"] for p in researcher["paragraphs"]] == ["Developed a multiplayer game in Unity (C#)."]
    assert extras == {"exp-cnpq-researcher": {"attachments": ["Certificate of presentation - Fulana.pdf"]}}
    assert warnings == []


def test_single_role_with_employment_type_after_company():
    [item], _, _ = parse_experience([block("Data Engineer", "Beta · Contract", "Jan 2023 - Dec 2023 · 1 yr",
                                           "Remote", "Built pipelines.")])

    assert (item["company"], item["work_mode"], item.get("location")) == ("Beta", "remote", None)


def test_role_without_description_gets_no_paragraphs_and_a_warning():
    items, _, warnings = parse_experience([block("Intern", "Gamma", "Jan 2020 - Jun 2020 · 6 mos")])

    assert items[0]["paragraphs"] == []
    assert any("sem descrição" in w for w in warnings)


def test_truncated_description_is_flagged():
    items, _, warnings = parse_experience([block("Dev", "Delta", "Jan 2021 - Present", "Did many things… more")])

    assert items[0]["paragraphs"][0]["text"] == "Did many things"
    assert any("cortada" in w for w in warnings)


def test_education_with_future_end_is_in_progress():
    items, warnings = parse_education([
        block("Universidade Exemplo", "Doctor's Degree, Artificial Intelligence", "Aug 2025 – Jul 2030"),
        block("Federal University", "Bachelor's Degree, Computer Engineering", "Mar 2019 – Feb 2024",
              "Skills: Data Modeling, +10 skills"),
        block("Technical School", "Technical Diploma", "2016 – 2018", "Grade: 9.5"),
    ], today="2026-10-28")

    phd, bachelor, technical = items
    assert phd == {"id": "edu-universidade-exemplo-doctor-s-degree", "institution": "Universidade Exemplo",
                   "degree": "Doctor's Degree", "field": "Artificial Intelligence", "start": "Aug 2025",
                   "end": "Present", "notes": "Expected Jul 2030"}
    assert (bachelor["end"], "notes" in bachelor) == ("Feb 2024", False)
    assert (technical["degree"], "field" in technical, technical["notes"]) == ("Technical Diploma", False, "Grade: 9.5")
    assert warnings == []


def test_volunteering():
    items, warnings = parse_volunteering([
        block("Events Director", "Student Association", "Jan 2022 - Apr 2022 · 4 mos", "Civil Rights and Social Action",
              "Organized events for 3,000 people."),
        block("Marketing Director", "Engineering Center", "Jun 2021 - Jun 2022 · 1 yr 1 mo", "Education"),
    ])

    assert items[0] == {"id": "vol-student-association-events-director", "organization": "Student Association",
                        "role": "Events Director", "start": "Jan 2022", "end": "Apr 2022",
                        "paragraphs": [{"id": "vol-student-association-events-director-p1",
                                        "text": "Organized events for 3,000 people."}]}
    assert items[1]["paragraphs"] == []
    assert warnings == []


def test_line_with_only_the_expander_does_not_become_a_paragraph():
    items, _ = parse_volunteering([block("Director", "Org", "Jan 2022 - Dec 2022", "Did things.", "… more")])

    assert [p["text"] for p in items[0]["paragraphs"]] == ["Did things."]
