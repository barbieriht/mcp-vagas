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


# --- perfil e critérios de triagem -------------------------------------------------------------

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from vagas.triage import parse_criteria  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "skill" / "candidaturas"


@pytest.fixture
def skill(tmp_path, monkeypatch):
    folder = tmp_path / "skill"
    folder.mkdir()
    for name in ("perfil.example.md", "criterios-triagem.example.md"):
        shutil.copy(EXAMPLES / name, folder / name)
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(folder))
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(folder / "criterios-triagem.md"))
    return folder


def section_fields(data, name):
    return {f["id"]: f for group in data["sections"][name]["groups"] for f in group["fields"]}


def test_profile_from_the_example_starts_empty_with_hints_and_documents_locked(db_path, skill):
    profile = section_fields(load(db_path), "profile")

    assert profile["Contato e identificação/Nome"]["value"] == ""
    assert profile["Contato e identificação/Nome"]["hint"] == "Fulano de Tal"  # exemplo vira dica, nunca valor
    assert profile["Contato e identificação/Data de nascimento"]["hint"] == "DD/MM/AAAA"
    assert profile["Outros campos de formulário/CPF"]["kind"] == "locked"
    assert profile["Respostas padrão/Incluir em bancos de talentos"]["kind"] == "yesno"
    assert not any(field_id.split("/")[-1].startswith("<") for field_id in profile)  # linha-modelo do exemplo
    assert not (skill / "perfil.md").exists()


def test_saving_the_profile_fills_what_was_typed_and_marks_the_rest_pending(db_path, skill):
    result = save({"profile": {"Contato e identificação/Nome": "Maria Teste",
                               "Respostas padrão/Incluir em bancos de talentos": "Não."}}, db_path)

    assert result["saved"], result["errors"]
    text = (skill / "perfil.md").read_text(encoding="utf-8")
    assert "- Nome: Maria Teste" in text and "- Incluir em bancos de talentos: não" in text
    assert "- Telefone: <PREENCHER>" in text and "Fulano" not in text
    assert "- CPF: informar manualmente" in text
    example = (skill / "perfil.example.md").read_text(encoding="utf-8")
    assert text.splitlines()[:5] == example.splitlines()[:5]  # cabeçalho e explicações do exemplo


def test_editing_the_profile_keeps_hand_written_extras_and_layout(db_path, skill):
    original = (EXAMPLES / "perfil.example.md").read_text(encoding="utf-8").replace("Fulano de Tal", "Maria Teste")
    original += "- Pretensão para PJ: conversar\n  - observação escrita à mão\n"
    (skill / "perfil.md").write_text(original, encoding="utf-8")

    fields = section_fields(load(db_path), "profile")
    result = save({"profile": {"Contato e identificação/Nome": "Maria Souza"}}, db_path)

    assert fields["Outros campos de formulário/Pretensão para PJ"]["value"] == "conversar"
    assert result["saved"]
    assert (skill / "perfil.md").read_text(encoding="utf-8") == original.replace("Maria Teste", "Maria Souza")


def test_profile_never_takes_a_document_value(db_path, skill):
    result = save({"profile": {"Outros campos de formulário/CPF": "529.982.247-25"}}, db_path)

    assert not result["saved"] and "Outros campos de formulário/CPF" in "".join(result["errors"])
    assert not (skill / "perfil.md").exists()


def test_profile_yes_no_field_only_takes_yes_or_no(db_path, skill):
    result = save({"profile": {"Respostas padrão/Incluir em bancos de talentos": "talvez"}}, db_path)

    assert result["errors"] == {"profile.Respostas padrão/Incluir em bancos de talentos": "Responda sim ou não."}


def test_criteria_from_the_example_offer_choices_and_save_a_valid_file(db_path, skill):
    criteria = section_fields(load(db_path), "criteria")

    roles = criteria["Cargos alvo"]
    assert roles["kind"] == "multi" and roles["value"] == ["data_scientist", "ml_engineer", "ai_engineer"]
    assert {c["value"] for c in roles["choices"]} >= {"data_scientist", "data_analyst"}
    assert criteria["Senioridades buscadas"]["kind"] == "multi"
    assert criteria["Aderência mínima"]["kind"] == "int"

    result = save({"criteria": {"Cargos alvo": ["data_scientist"], "Senioridades buscadas": ["pleno", "senior"],
                                "Vagas afirmativas que posso disputar": ["women"], "Aderência mínima": "60",
                                "Empresas ignoradas": "Acme, Outra S.A."}}, db_path)

    assert result["saved"], result["errors"]
    saved = parse_criteria((skill / "criterios-triagem.md").read_text(encoding="utf-8"))
    assert saved.target_roles == ("data_scientist",) and saved.search_seniorities == ("pleno", "senior")
    assert saved.affirmative_ok == ("women",) and saved.min_match == 60
    assert "## Valores aceitos" in (skill / "criterios-triagem.md").read_text(encoding="utf-8")


def test_criteria_errors_come_back_for_every_bad_field(db_path, skill):
    result = save({"criteria": {"Cargos alvo": [], "Aderência mínima": "150",
                                "Estados aceitos para híbrido e presencial": "Narnia"}}, db_path)

    assert not result["saved"]
    assert set(result["errors"]) == {"criteria.Cargos alvo", "criteria.Aderência mínima",
                                     "criteria.Estados aceitos para híbrido e presencial"}
    assert not (skill / "criterios-triagem.md").exists()


def test_criteria_written_by_hand_with_names_are_read_as_choices(db_path, skill):
    text = (EXAMPLES / "criterios-triagem.example.md").read_text(encoding="utf-8")
    text = text.replace("- Cargos alvo: data_scientist, ml_engineer, ai_engineer", "- Cargos alvo: Cientista de Dados.")
    text = text.replace("- Senioridades buscadas:", "- Senioridades buscadas: Júnior, Sênior")
    (skill / "criterios-triagem.md").write_text(text, encoding="utf-8")

    criteria = section_fields(load(db_path), "criteria")

    assert criteria["Cargos alvo"]["value"] == ["data_scientist"]
    assert criteria["Senioridades buscadas"]["value"] == ["junior", "senior"]


def test_one_invalid_section_saves_no_section(db_path, skill, tmp_path):
    result = save({"config": {"export_dir": str(tmp_path / "csv")},
                   "profile": {"Contato e identificação/Nome": "Maria"},
                   "criteria": {"Cargos alvo": []}}, db_path)

    assert not result["saved"]
    assert not config_path(db_path).exists() and not (skill / "perfil.md").exists()


def test_without_the_skill_folder_the_sections_explain_what_to_do(db_path, monkeypatch):
    monkeypatch.delenv("VAGAS_SKILL_DIR", raising=False)
    monkeypatch.delenv("VAGAS_TRIAGE_CRITERIA", raising=False)

    data = load(db_path)

    assert "VAGAS_SKILL_DIR" in data["sections"]["profile"]["error"]
    assert data["sections"]["profile"]["groups"] == []


def test_talent_pool_is_yes_or_no_even_without_the_note(db_path, skill):
    text = (EXAMPLES / "perfil.example.md").read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if "Valores aceitos: sim ou não" not in line) + "\n"
    (skill / "perfil.md").write_text(text.replace("- Incluir em bancos de talentos: <...>",
                                                  "- Incluir em bancos de talentos: Sim."), encoding="utf-8")

    field = section_fields(load(db_path), "profile")["Respostas padrão/Incluir em bancos de talentos"]

    assert field["kind"] == "yesno" and field["value"] == "sim"


# --- diversidade: um campo de escolha para cada pergunta -------------------------------------

LEGACY_DIVERSITY = """## Respostas padrão
- Diversidade:
  - Sexo Masculino
  - Homem cisgênero
  - Heterossexual
  - Branco/Latino
- Parentes na empresa: não
"""


def diversity(data):
    fields = section_fields(data, "profile")
    return {f["title"]: f for f in fields.values() if (f["parent"] or "").startswith("Diversidade")}


def test_diversity_has_one_choice_per_question_with_prefer_not_and_other(db_path, skill):
    fields = diversity(load(db_path))

    assert set(fields) == {"Sexo", "Identidade de gênero", "Orientação sexual", "Raça/etnia"}
    for field in fields.values():
        assert field["kind"] == "choice_other"
        assert "Prefiro não responder" in field["choices"] and len(field["choices"]) >= 4
    assert "Mulher transgênera" in fields["Identidade de gênero"]["choices"]
    assert {"Branca", "Preta", "Parda", "Amarela", "Indígena"} <= set(fields["Raça/etnia"]["choices"])


def test_answers_written_as_loose_lines_are_recognized(db_path, skill):
    (skill / "perfil.md").write_text(LEGACY_DIVERSITY, encoding="utf-8")

    fields = diversity(load(db_path))

    assert fields["Sexo"]["value"] == "Masculino"
    assert fields["Identidade de gênero"]["value"] == "Homem cisgênero"
    assert fields["Orientação sexual"]["value"] == "Heterossexual"
    assert fields["Raça/etnia"]["value"] == "Branco/Latino"  # fora das opções: vira "Outra", sem perder o texto


def test_changing_one_answer_rewrites_the_block_as_one_field_per_question(db_path, skill):
    (skill / "perfil.md").write_text(LEGACY_DIVERSITY, encoding="utf-8")
    fid = diversity(load(db_path))["Sexo"]["id"]

    result = save({"profile": {fid: "Prefiro não responder"}}, db_path)

    assert result["saved"], result["errors"]
    assert (skill / "perfil.md").read_text(encoding="utf-8") == """## Respostas padrão
- Diversidade:
  - Sexo: Prefiro não responder
  - Identidade de gênero: Homem cisgênero
  - Orientação sexual: Heterossexual
  - Raça/etnia: Branco/Latino
- Parentes na empresa: não
"""


def test_pcd_terms_are_not_a_user_setting_anymore(db_path, skill):
    criteria = section_fields(load(db_path), "criteria")

    assert not any("PcD" in fid for fid in criteria)
    assert "Termos de vaga exclusiva PcD" not in (EXAMPLES / "criterios-triagem.example.md").read_text(encoding="utf-8")
