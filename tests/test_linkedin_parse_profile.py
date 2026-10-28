from vagas.linkedin_parse import parse_languages, parse_profile, parse_skills

PROFILE = """Fulana de Tal
She/Her
Data Scientist | ML Engineer | Remote / Cidade, UF
Universidade Exemplo
Cidade, Estado, Brazil
·
Contact info
500+ connections
Open to work · Recruiters only
About
I'm a data scientist working with LLM applications.
Most recently I built ETL pipelines in Python.
Top skills
Python • SQL
Activity
Experience
Analyst"""

LANGUAGES = """Languages
English
Professional working proficiency
Português
Native or bilingual proficiency
Spanish
Limited working proficiency
Who your viewers also viewed
Private to you
Someone
· 2nd"""


def test_profile_headline_and_about():
    assert parse_profile(PROFILE) == {
        "headline": "Data Scientist | ML Engineer | Remote / Cidade, UF",
        "summary": "I'm a data scientist working with LLM applications.\n\nMost recently I built ETL pipelines in Python.",
    }


def test_profile_without_pronouns_and_about():
    assert parse_profile("Fulana\nData Scientist\nContact info\nExperience") == {"headline": "Data Scientist"}


def test_truncated_about_is_cleaned():
    assert parse_profile("Fulana\nHeadline\nAbout\nText cut here… see more\nExperience")["summary"] == "Text cut here"


def test_languages_from_page_text():
    assert parse_languages(LANGUAGES) == [
        {"name": "English", "level": "Professional working proficiency"},
        {"name": "Português", "level": "Native or bilingual proficiency"},
        {"name": "Spanish", "level": "Limited working proficiency"},
    ]


def test_skills_first_line_of_each_block_deduplicated():
    blocks = [{"lines": ["Python", "Course A"]}, {"lines": ["SQL"]}, {"lines": ["Python"]}, {"lines": []},
              {"lines": ["All"]}, {"lines": ["Industry Knowledge"]}]

    assert parse_skills(blocks) == [{"id": "skills-linkedin", "label": "Skills (LinkedIn)", "terms": ["Python", "SQL"]}]
    assert parse_skills([]) == []


def test_headline_from_live_page_text_with_navigation_before_the_card():
    text = ("0 notifications\nSkip to search\nHome\nJobs\nData Scientist | ML Engineer\nResources\nOpen to\n"
            "Fulana de Tal\nShe/Her\nData Scientist | ML Engineer\nCidade, Estado, Brazil\n·\nContact info\n"
            "About\nI build pipelines.\nActivity")

    assert parse_profile(text) == {"headline": "Data Scientist | ML Engineer", "summary": "I build pipelines."}


def test_headline_without_pronouns_skips_location():
    text = "Home\nFulana\nData Scientist | ML\nCidade, Estado, Brazil\n·\nContact info"

    assert parse_profile(text)["headline"] == "Data Scientist | ML"
