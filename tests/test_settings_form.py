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


# --- política salarial ---------------------------------------------------------------------------

from vagas.salary_policy import parse_policy  # noqa: E402

POLICY_TEXT = """# Política salarial

Explicação que precisa ficar.

- Modo: minimo
  - minimo: aplicar se a mediana for maior ou igual ao mínimo
- Multiplicador PJ: 1.4
- Remoto nacional (BRL, CLT): mínimo 8.000, máximo 12.000
- Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10.500
- Híbrido/presencial em Campinas (BRL, CLT): usar a faixa do remoto nacional
- Internacional (USD): mínimo 3000

## Valores aceitos
- **Modo:** `minimo` ou `faixa`.
"""


@pytest.fixture
def policy(tmp_path, monkeypatch, skill):
    shutil.copy(EXAMPLES / "politica-salarial.example.md", skill / "politica-salarial.example.md")
    path = skill / "politica-salarial.md"
    monkeypatch.setenv("VAGAS_SALARY_POLICY", str(path))
    return path


def policy_section(db_path):
    return {f["id"]: f for g in load(db_path)["sections"]["policy"]["groups"] for f in g["fields"]}


def test_policy_shows_mode_multiplier_and_one_row_per_band(db_path, policy):
    policy.write_text(POLICY_TEXT, encoding="utf-8")

    fields = policy_section(db_path)

    assert fields["Modo"]["kind"] == "choice" and fields["Modo"]["value"] == "minimo"
    assert fields["Multiplicador PJ"]["value"] == "1.4"
    bands = fields["Faixas"]
    assert bands["kind"] == "bands" and bands["currencies"] == ["BRL", "USD", "EUR"]
    assert [(b["name"], b["currency"], b["clt"], b["min"], b["max"], b["alias"]) for b in bands["value"]] == [
        ("Remoto nacional", "BRL", True, "8000", "12000", ""),
        ("Híbrido/presencial em São Paulo e região", "BRL", True, "10500", "", ""),
        ("Híbrido/presencial em Campinas", "BRL", True, "", "", "remoto nacional"),
        ("Internacional", "USD", False, "3000", "", ""),
    ]
    assert bands["value"][1]["applies"] == "Vale para vagas híbridas e presenciais em São Paulo."
    assert bands["value"][3]["applies"] == "Vale para vagas remotas, híbridas e presenciais em qualquer local."


def test_saving_bands_rewrites_only_the_band_lines_in_place(db_path, policy):
    policy.write_text(POLICY_TEXT, encoding="utf-8")
    bands = policy_section(db_path)["Faixas"]["value"]
    bands[0]["min"] = "9000"
    del bands[3]
    bands.append({"name": "Presencial em Curitiba", "currency": "BRL", "clt": False, "min": "R$ 11.000,00",
                  "max": "14000", "alias": ""})

    result = save({"policy": {"Faixas": bands, "Multiplicador PJ": "1,5"}}, db_path)

    assert result["saved"], result["errors"]
    text = policy.read_text(encoding="utf-8")
    assert text == POLICY_TEXT.replace("- Multiplicador PJ: 1.4", "- Multiplicador PJ: 1,5").replace(
        "- Remoto nacional (BRL, CLT): mínimo 8.000, máximo 12.000\n"
        "- Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10.500\n"
        "- Híbrido/presencial em Campinas (BRL, CLT): usar a faixa do remoto nacional\n"
        "- Internacional (USD): mínimo 3000\n",
        "- Remoto nacional (BRL, CLT): mínimo 9000, máximo 12000\n"
        "- Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10500\n"
        "- Híbrido/presencial em Campinas (BRL, CLT): usar a faixa do remoto nacional\n"
        "- Presencial em Curitiba (BRL): mínimo 11000, máximo 14000\n")
    assert len(parse_policy(text).bands) == 4


def test_each_bad_band_comes_back_with_its_own_error(db_path, policy):
    policy.write_text(POLICY_TEXT, encoding="utf-8")
    before = policy.read_text(encoding="utf-8")
    bands = [
        {"name": "Remoto", "currency": "BRL", "clt": True, "min": "", "max": "", "alias": ""},
        {"name": "Híbrido", "currency": "XYZ", "clt": False, "min": "9000", "max": "", "alias": ""},
        {"name": "Presencial", "currency": "BRL", "clt": False, "min": "9000", "max": "8000", "alias": ""},
        {"name": "Outra (teste)", "currency": "BRL", "clt": False, "min": "", "max": "", "alias": "inexistente"},
    ]

    result = save({"policy": {"Faixas": bands, "Multiplicador PJ": "zero"}}, db_path)

    assert not result["saved"] and policy.read_text(encoding="utf-8") == before
    assert set(result["errors"]) == {"policy.Faixas.0.min", "policy.Faixas.1.currency", "policy.Faixas.2.max",
                                     "policy.Faixas.3.name", "policy.Faixas.3.alias", "policy.Multiplicador PJ"}


def test_range_mode_needs_a_maximum_in_every_band(db_path, policy):
    policy.write_text(POLICY_TEXT, encoding="utf-8")

    result = save({"policy": {"Modo": "faixa"}}, db_path)

    assert not result["saved"]
    assert {"policy.Faixas.1.max", "policy.Faixas.3.max"} <= set(result["errors"])


def test_at_least_one_band_is_needed(db_path, policy):
    policy.write_text(POLICY_TEXT, encoding="utf-8")

    result = save({"policy": {"Faixas": []}}, db_path)

    assert result["errors"] == {"policy.Faixas": "Cadastre pelo menos uma faixa."}


def test_new_policy_keeps_the_example_bands_but_not_its_values(db_path, policy):
    bands = policy_section(db_path)["Faixas"]

    assert [b["name"] for b in bands["value"]][:2] == ["Remoto nacional", "Híbrido/presencial em São Paulo e região"]
    assert all(b["min"] == "" and b["max"] == "" for b in bands["value"])
    assert bands["value"][0]["hint_min"] == "8000"
    blocked = save({"policy": {"Faixas": bands["value"]}}, db_path)
    assert not blocked["saved"] and "policy.Faixas.0.min" in blocked["errors"]
    assert not policy.exists()


def test_changing_the_policy_reevaluates_the_open_applications(db_path, policy, monkeypatch):
    policy.write_text(POLICY_TEXT, encoding="utf-8")
    calls = []
    monkeypatch.setattr("vagas.settings_form._reevaluate_salaries", lambda db: calls.append(db) or {"changed": []})

    save({"profile": {}}, db_path)  # nada da política: não reavalia
    result = save({"policy": {"Multiplicador PJ": "1.5"}}, db_path)

    assert calls == [db_path] and result["reevaluated"] == {"changed": []}


# --- campos novos do exemplo num perfil que já existe ------------------------------------------

def test_the_example_has_a_portfolio_for_people_outside_tech():
    lines = (EXAMPLES / "perfil.example.md").read_text(encoding="utf-8").splitlines()

    assert any(line.startswith("- Portfólio:") for line in lines)
    assert lines.index(next(l for l in lines if l.startswith("- Portfólio:"))) == \
        lines.index(next(l for l in lines if l.startswith("- GitHub:"))) + 1


def test_fields_of_the_example_missing_from_the_profile_show_up_and_are_added_only_when_filled(db_path, skill):
    original = "## Contato e identificação\n- Nome: Maria Teste\n- GitHub: https://github.com/maria\n\n## Respostas padrão\n- Parentes na empresa: não\n"
    (skill / "perfil.md").write_text(original, encoding="utf-8")

    portfolio = section_fields(load(db_path), "profile")["Contato e identificação/Portfólio"]
    untouched = save({"profile": {"Contato e identificação/Nome": "Maria Souza"}}, db_path)
    after_name = (skill / "perfil.md").read_text(encoding="utf-8")
    filled = save({"profile": {"Contato e identificação/Portfólio": "https://behance.net/maria"}}, db_path)

    assert portfolio["value"] == "" and portfolio["missing"]
    assert untouched["saved"] and "Portfólio" not in after_name
    assert filled["saved"], filled["errors"]
    assert (skill / "perfil.md").read_text(encoding="utf-8") == (
        "## Contato e identificação\n- Nome: Maria Souza\n- GitHub: https://github.com/maria\n"
        "- Portfólio: https://behance.net/maria\n\n## Respostas padrão\n- Parentes na empresa: não\n")


# --- documentos do cofre -----------------------------------------------------------------------

import json as _json  # noqa: E402

from test_sensitive import FakeBackend  # noqa: E402
from vagas.sensitive import NoVaultBackend, Vault  # noqa: E402


@pytest.fixture
def vault(tmp_path, monkeypatch, skill):
    shutil.copy(EXAMPLES / "perfil.example.md", skill / "perfil.md")
    path = tmp_path / "cofre.json"
    monkeypatch.setenv("VAGAS_SENSITIVE_FILE", str(path))
    monkeypatch.setattr("vagas.settings_files._vault_backend", FakeBackend)
    return Vault(path, FakeBackend())


def vault_fields(data):
    return {f["id"]: f for g in data["sections"]["vault"]["groups"] for f in g["fields"]}


def test_vault_lists_every_document_and_only_says_which_are_stored(db_path, vault):
    vault.set("rg", "12.345.678-9")

    data = load(db_path)
    fields = vault_fields(data)

    assert set(fields) == {"cpf", "rg", "rg_orgao_emissor", "cnh", "pis", "ctps", "titulo_eleitor", "passaporte",
                           "nome_mae"}
    assert fields["rg"]["stored"] and not fields["cpf"]["stored"] and fields["cpf"]["kind"] == "secret"
    assert "12.345.678-9" not in _json.dumps(data) and "12345678" not in _json.dumps(data)


def test_storing_a_document_never_echoes_it_and_marks_the_profile(db_path, vault, skill):
    result = save({"vault": {"set": {"cpf": "529.982.247-25"}}}, db_path)

    assert result["saved"], result["errors"]
    assert vault.get("cpf") == "52998224725"
    assert "52998224725" not in _json.dumps(result) and "529.982" not in _json.dumps(result)
    assert "- CPF: no cofre" in (skill / "perfil.md").read_text(encoding="utf-8")


def test_invalid_cpf_stores_nothing(db_path, vault):
    result = save({"vault": {"set": {"cpf": "111.111.111-11", "rg": "12.345.678-9"}}}, db_path)

    assert result["errors"] == {"vault.cpf": "CPF inválido: os dígitos verificadores não conferem."}
    assert vault.list() == []


def test_removing_a_document_clears_it_and_the_profile_mark(db_path, vault, skill):
    save({"vault": {"set": {"cpf": "529.982.247-25"}}}, db_path)

    result = save({"vault": {"remove": ["cpf"]}}, db_path)

    assert result["saved"] and vault.list() == []
    assert "- CPF: informar manualmente" in (skill / "perfil.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", [{"set": {"senha": "x"}}, {"set": {"cpf": ""}}, {"remove": ["banco"]},
                                 {"set": {"rg": "1\n2"}}, "texto"])
def test_vault_refuses_anything_outside_the_allowed_documents(db_path, vault, bad):
    result = save({"vault": bad}, db_path)

    assert not result["saved"] and result["errors"] and vault.list() == []


def test_without_a_keyring_the_vault_explains_and_refuses(db_path, vault, monkeypatch):
    monkeypatch.setattr("vagas.settings_files._vault_backend", NoVaultBackend)

    section = load(db_path)["sections"]["vault"]
    result = save({"vault": {"set": {"rg": "12.345.678-9"}}}, db_path)

    assert "secret-tool" in section["unavailable"]
    assert not result["saved"] and "secret-tool" in result["errors"]["vault"]
