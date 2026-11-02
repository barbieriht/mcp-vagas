import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "instalar_claude_code.py"
spec = importlib.util.spec_from_file_location("instalar_claude_code", SCRIPT)
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)
REPO = Path(__file__).resolve().parents[1]


def test_skill_dirs_are_main_skill_and_every_command():
    names = [d.name for d in inst.skill_dirs(REPO)]

    assert names[0] == "candidaturas"
    assert set(names[1:]) == {"generate-master-resume", "search-jobs", "apply", "screen", "work-list", "pending",
                              "export-applications"}


def test_link_is_created_kept_and_fixed(tmp_path):
    target, other = tmp_path / "skill", tmp_path / "other"
    target.mkdir()
    other.mkdir()
    link = tmp_path / "home" / "skills" / "skill"

    assert inst.ensure_link(link, target) == "criado"
    assert inst.ensure_link(link, target) == "ok"
    link.unlink()
    link.symlink_to(other)
    assert inst.ensure_link(link, target) == "atualizado"
    assert link.resolve() == target.resolve()


def test_real_directory_is_never_replaced(tmp_path):
    target = tmp_path / "skill"
    target.mkdir()
    real = tmp_path / "skills" / "skill"
    real.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        inst.ensure_link(real, target)
    assert real.is_dir() and not real.is_symlink()


def test_mcp_registration_detection(tmp_path):
    claude_json = tmp_path / ".claude.json"
    assert inst.mcp_registered(claude_json) is False
    claude_json.write_text('{"mcpServers": {"vagas": {}}}')
    assert inst.mcp_registered(claude_json) is True


def test_personal_links_point_from_next_to_the_db_to_the_skill(tmp_path):
    links = inst.personal_links(tmp_path / "data", REPO)

    assert links == [(tmp_path / "data" / name, REPO / "skill" / "candidaturas" / name)
                     for name in ("politica-salarial.md", "criterios-triagem.md")]
