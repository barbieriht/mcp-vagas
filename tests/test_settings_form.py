"""Formulário de configuração do painel (sem HTTP): ler, validar e gravar tudo ou nada."""

import tomllib

import pytest

from vagas.config import config_path, resolve
from vagas.settings_form import load, save


def fields(data):
    return {field["key"]: field for field in data["sections"]["config"]["fields"]}


def written(db_path):
    path = config_path(db_path)
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def test_load_shows_every_setting_with_value_source_and_suggestions(db_path):
    data = load(db_path)

    config = fields(data)
    assert set(config) >= {"resume_out", "export_dir", "master_resume", "login_method", "salary_rule"}
    assert config["resume_out"]["value"] == "" and config["resume_out"]["source"] == "unset"
    assert config["resume_out"]["kind"] == "dir" and config["resume_out"]["suggestions"]
    assert config["login_method"]["choices"] == [{"value": "linkedin", "label": "LinkedIn"},
                                                 {"value": "google", "label": "Google"}]
    assert all(field["title"] != field["key"] for field in config.values())  # todo campo tem nome legível
    assert config["export_dir"]["default"] == str(db_path.parent / "exports")
    assert "resume_out" in data["sections"]["config"]["needs_setup"]


def test_saving_writes_everything_creates_the_folders_and_stops_asking(db_path, tmp_path):
    result = save({"config": {"resume_out": str(tmp_path / "pdfs"), "login_method": "Gmail",
                              "max_open_tabs": "8", "auto_submit": "não"}}, db_path)

    assert result["saved"] and result["errors"] == {}
    assert written(db_path) == {"resume_out": str(tmp_path / "pdfs"), "login_method": "google",
                                "max_open_tabs": 8, "auto_submit": "nao"}
    assert (tmp_path / "pdfs").is_dir()
    assert "resume_out" not in result["settings"]["sections"]["config"]["needs_setup"]


def test_any_invalid_field_saves_nothing_and_points_to_each_field(db_path, tmp_path):
    save({"config": {"export_dir": str(tmp_path / "csv")}}, db_path)
    before = config_path(db_path).read_text(encoding="utf-8")

    result = save({"config": {"export_dir": str(tmp_path / "outra"), "resume_out": "pasta/relativa",
                              "max_open_tabs": "99", "login_email": "não é e-mail"}}, db_path)

    assert not result["saved"]
    assert set(result["errors"]) == {"config.resume_out", "config.max_open_tabs", "config.login_email"}
    assert "absoluto" in result["errors"]["config.resume_out"]
    assert config_path(db_path).read_text(encoding="utf-8") == before
    assert not (tmp_path / "outra").exists()


def test_clearing_a_field_goes_back_to_the_default(db_path, tmp_path):
    save({"config": {"export_dir": str(tmp_path / "csv"), "login_email": "nome@gmail.com"}}, db_path)

    save({"config": {"export_dir": "", "login_email": ""}}, db_path)

    assert written(db_path) == {}
    assert resolve("export_dir", db_path) == (db_path.parent / "exports", "default")


def test_fields_left_out_of_the_form_are_kept(db_path, tmp_path):
    save({"config": {"export_dir": str(tmp_path / "csv")}}, db_path)

    save({"config": {"max_open_tabs": "5"}}, db_path)

    assert written(db_path) == {"export_dir": str(tmp_path / "csv"), "max_open_tabs": 5}


def test_unknown_keys_are_refused(db_path):
    result = save({"config": {"outra_coisa": "x"}, "segredo": {}}, db_path)

    assert not result["saved"] and set(result["errors"]) == {"config.outra_coisa", "segredo"}
    assert not config_path(db_path).exists()


def test_environment_variable_that_overrides_a_value_is_shown(db_path, monkeypatch, tmp_path):
    monkeypatch.setenv("VAGAS_RESUME_OUT", str(tmp_path / "env"))

    config = fields(load(db_path))
    result = save({"config": {"resume_out": str(tmp_path / "pdfs")}}, db_path)

    assert config["resume_out"]["source"] == "env" and config["resume_out"]["env"] == "VAGAS_RESUME_OUT"
    assert config["resume_out"]["effective"] == str(tmp_path / "env")
    assert result["saved"] and "VAGAS_RESUME_OUT" in result["warnings"][0]


def test_changing_the_salary_rule_reevaluates_the_open_applications(db_path, monkeypatch):
    calls = []
    monkeypatch.setattr("vagas.settings_form._reevaluate_salaries", lambda db: calls.append(db) or {"changed": []})

    save({"config": {"max_open_tabs": "5"}}, db_path)
    result = save({"config": {"salary_rule": "meio termo"}}, db_path)
    save({"config": {"salary_rule": "meio_termo"}}, db_path)  # sem mudança: não reavalia

    assert calls == [db_path] and result["reevaluated"] == {"changed": []}


@pytest.mark.parametrize("bad", [None, [], "texto", {"config": "texto"}, {"config": {"max_open_tabs": 5}}])
def test_malformed_payload_is_a_readable_error(db_path, bad):
    result = save(bad, db_path)

    assert not result["saved"] and result["errors"]
