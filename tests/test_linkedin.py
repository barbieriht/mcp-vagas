import pytest

from vagas.linkedin import LinkedInError, detail_urls, is_blocked, profile_base


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/in/fulana/",
    "linkedin.com/in/fulana",
    "https://br.linkedin.com/in/fulana?trk=public_profile",
    "https://www.linkedin.com/in/fulana/details/certifications/",
])
def test_profile_base_is_canonical(url):
    assert profile_base(url) == "https://www.linkedin.com/in/fulana/"


@pytest.mark.parametrize("url", ["https://www.linkedin.com/company/acme/", "https://example.com/in/x", ""])
def test_non_profile_urls_are_rejected(url):
    with pytest.raises(LinkedInError, match="perfil"):
        profile_base(url)


def test_detail_urls():
    urls = detail_urls("https://www.linkedin.com/in/fulana/")

    assert urls["certifications"] == "https://www.linkedin.com/in/fulana/details/certifications/"
    assert urls["volunteering-experiences"] == "https://www.linkedin.com/in/fulana/details/volunteering-experiences/"
    assert set(urls) == {"experience", "education", "certifications", "volunteering-experiences", "languages", "skills"}


@pytest.mark.parametrize("url, blocked", [
    ("https://www.linkedin.com/login?session_redirect=x", True),
    ("https://www.linkedin.com/checkpoint/challenge/abc", True),
    ("https://www.linkedin.com/authwall?trk=x", True),
    ("https://www.linkedin.com/feed/", False),
    ("https://www.linkedin.com/in/fulana/details/certifications/", False),
])
def test_blocked_pages_are_detected(url, blocked):
    assert is_blocked(url) is blocked
