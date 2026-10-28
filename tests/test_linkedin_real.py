"""Leitura real do perfil do LinkedIn (opt-in). Defina VAGAS_TEST_LINKEDIN_PROFILE com a URL do próprio
perfil e faça o login antes (python -m vagas.linkedin login). Grava só num banco temporário."""

import os

import pytest

PROFILE = os.environ.get("VAGAS_TEST_LINKEDIN_PROFILE")
pytestmark = pytest.mark.skipif(not PROFILE, reason="defina VAGAS_TEST_LINKEDIN_PROFILE para ler o perfil real")


def test_real_profile_is_read_completely(db_path, tmp_path):
    pytest.importorskip("playwright")
    from vagas.db import connect
    from vagas.linkedin import LinkedInReader
    from vagas.linkedin_import import LinkedInImporter
    from vagas.resume_repo import ResumeStore

    store = ResumeStore(connect(db_path), tmp_path / "curriculo.yaml")
    result = LinkedInImporter(store, LinkedInReader()).import_profile(PROFILE)

    read = {section: c["read"] for section, c in result["completeness"].items()}
    assert all(count > 0 for count in read.values()), read
    assert result["items"].get("headline") and result["items"].get("summary")
    certifications = [i for g in result["items"]["certifications"] for i in g["items"]]
    assert sum("link" in i for i in certifications) >= 0.8 * len(certifications)
    assert all("issued" in i for i in certifications)
    assert not [w for w in result["warnings"] if "cortada" in w], result["warnings"]
    items = dict(result["items"])
    basics = {"name": "x", "headline": items.pop("headline")}
    assert store.save_master_draft({"basics": basics, **items})["review"] == []
