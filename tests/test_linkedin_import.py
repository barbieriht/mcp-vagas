from datetime import datetime, timedelta, timezone

import pytest

from vagas.db import connect
from vagas.linkedin import LinkedInError
from vagas.linkedin_import import LinkedInImporter
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore

T0 = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
PROFILE = "https://br.linkedin.com/in/fulana?trk=x"
CERTS = [
    {"lines": ["Licenses & certifications"], "links": []},
    {"lines": ["Course A", "Alura", "Issued Mar 2025", "Credential ID A-1", "Show credential"],
     "links": [{"text": "Show credential", "href": "https://cursos.alura.com.br/certificate/a1"}]},
    {"lines": ["Course B", "LinkedIn", "Issued Oct 2026"], "links": []},
]


EXPERIENCE = [{"lines": ["Analyst", "Acme · Full-time", "Feb 2024 - Present · 1 yr", "Remote",
                         "Maintained ETL pipelines."], "links": []}]
EDUCATION = [{"lines": ["Universidade Exemplo", "Doctor's Degree, AI", "Aug 2025 – Jul 2030"], "links": []}]
VOLUNTEERING = [{"lines": ["Events Director", "Student Association", "Jan 2022 - Apr 2022 · 4 mos",
                           "Organized events."], "links": []}]


class FakeReader:
    def __init__(self, blocks=None, error=None, sections=None):
        self.error, self.calls = error, []
        self.sections = sections or {"certifications": blocks if blocks is not None else CERTS,
                                     "experience": EXPERIENCE, "education": EDUCATION, "volunteering": VOLUNTEERING}

    def read_sections(self, url, sections):
        self.calls.append((url, tuple(sections)))
        if self.error:
            raise self.error
        return self.sections


class Clock:
    def __init__(self):
        self.at = T0

    def __call__(self):
        return self.at.isoformat(timespec="seconds")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(db_path, tmp_path, clock):
    conn = connect(db_path)
    yield ResumeStore(conn, tmp_path / "curriculo.yaml", now=clock)
    conn.close()


def test_imports_certifications_and_registers_source(store):
    reader = FakeReader()

    result = LinkedInImporter(store, reader).import_profile(PROFILE)

    assert reader.calls == [("https://www.linkedin.com/in/fulana/",
                              ("experience", "education", "certifications", "volunteering"))]
    groups = result["items"]["certifications"]
    assert [i["name"] for g in groups for i in g["items"]] == ["Course A", "Course B"]
    assert result["completeness"]["certifications"] == {"read": 2, "expected": None, "verified": False}
    assert {s: c["read"] for s, c in result["completeness"].items()} == {
        "experience": 1, "education": 1, "certifications": 2, "volunteering": 1}
    assert result["items"]["experience"][0]["work_mode"] == "remote"
    assert result["items"]["education"][0]["end"] == "Present"
    assert result["warnings"] == []
    draft = store.save_master_draft({"basics": {"name": "Course A"}, **result["items"]})
    assert draft["sources"] == [{"kind": "linkedin", "path": "https://www.linkedin.com/in/fulana/"}]
    assert draft["review"] == []


def test_minimum_interval_between_reads(store, clock, monkeypatch):
    monkeypatch.delenv("VAGAS_LINKEDIN_MIN_MINUTES", raising=False)
    importer = LinkedInImporter(store, FakeReader())
    importer.import_profile(PROFILE)

    clock.at = T0 + timedelta(minutes=59)
    with pytest.raises(VagasError, match="intervalo"):
        importer.import_profile(PROFILE)

    clock.at = T0 + timedelta(minutes=60)
    assert importer.import_profile(PROFILE)["items"]


def test_interval_is_configurable(store, clock, monkeypatch):
    monkeypatch.setenv("VAGAS_LINKEDIN_MIN_MINUTES", "5")
    importer = LinkedInImporter(store, FakeReader())
    importer.import_profile(PROFILE)
    clock.at = T0 + timedelta(minutes=6)

    assert importer.import_profile(PROFILE)["items"]


@pytest.mark.parametrize("message", ["O LinkedIn pediu login ou verificação de segurança", "Playwright não instalado"])
def test_reader_problems_become_readable_errors_and_nothing_is_registered(store, message):
    with pytest.raises(VagasError, match=message):
        LinkedInImporter(store, FakeReader(error=LinkedInError(message))).import_profile(PROFILE)

    assert store.save_master_draft({"basics": {"name": "x"}})["sources"] == []


def test_non_profile_url_is_rejected(store):
    with pytest.raises(VagasError, match="perfil"):
        LinkedInImporter(store, FakeReader()).import_profile("https://www.linkedin.com/company/acme/")


def test_empty_section_is_a_warning(store):
    result = LinkedInImporter(store, FakeReader(blocks=[])).import_profile(PROFILE)

    assert result["completeness"]["certifications"]["read"] == 0
    assert any("nenhum item" in w.lower() for w in result["warnings"])
