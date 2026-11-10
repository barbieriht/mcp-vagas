"""Formulário de configuração do painel local: ler, validar e gravar tudo ou nada. Não depende de HTTP.

O painel (vagas.panel) só transporta o dicionário: load() devolve as seções com os valores atuais, e
save() valida tudo antes de gravar qualquer coisa. Os erros voltam por campo, como "config.resume_out",
com a mesma mensagem que o set_config daria. Os arquivos continuam sendo a fonte da verdade.
"""

from pathlib import Path
from typing import Any

from vagas import config, md_fields, settings_files
from vagas.repo import VagasError

# Seções que editam arquivos em Markdown: chave -> (load, plan).
FILE_SECTIONS = {
    "profile": (settings_files.load_profile, settings_files.plan_profile),
    "criteria": (settings_files.load_criteria, settings_files.plan_criteria),
    "policy": (settings_files.load_policy, settings_files.plan_policy),
    "vault": (settings_files.load_vault, settings_files.plan_vault),
}


# Nomes curtos para o painel; o label do SETTINGS vira o texto de ajuda.
_TITLES = {
    "resume_out": "Pasta dos currículos em PDF", "export_dir": "Pasta dos CSVs exportados",
    "master_resume": "Arquivo do currículo geral (YAML)", "login_method": "Login preferido nos sites de vagas",
    "login_email": "Conta Google para login", "max_open_tabs": "Abas de candidatura abertas, no máximo",
    "auto_submit": "Envio automático", "autofill_domains": "Domínios extras da extensão do Chrome",
    "autofill_platforms": "Plataformas com permissão para todas as empresas",
    "salary_rule": "Regra da pretensão salarial",
}
_CHOICE_LABELS = {
    "linkedin": "LinkedIn", "google": "Google", "sim": "Ligado", "nao": "Desligado",
    "teto": "Teto: a mediana de mercado", "meio_termo": "Meio-termo entre o seu mínimo e a mediana",
    "percentil_25": "Percentil 25 do mercado", "ponto_baixo": "Ponto mais baixo de cada fonte",
}


def _config_section(db_path: Path | str | None) -> dict[str, Any]:
    described = config.describe(db_path)
    stored = config.load(db_path)
    fields = []
    for key, info in described["settings"].items():
        setting = config.SETTINGS[key]
        fields.append({
            "key": key, "title": _TITLES.get(key, key), "label": setting.label, "kind": setting.kind,
            "choices": [{"value": c, "label": _CHOICE_LABELS.get(c, c)} for c in setting.choices],
            "value": stored.get(key, ""), "effective": info["value"] or "", "source": info["source"],
            "default": info["default"] or "", "env": setting.env, "suggestions": info["suggestions"],
            "bounds": list(setting.bounds) if setting.kind == "int" else None,
        })
    return {"title": "Pastas e opções", "file": described["config_file"], "fields": fields,
            "needs_setup": described["needs_setup"]}


def load(db_path: Path | str | None = None) -> dict[str, Any]:
    """Seções do painel com os valores atuais: config (config.toml), profile (perfil.md) e criteria
    (criterios-triagem.md). Uma seção cujo arquivo não é encontrado volta com "error" e sem campos."""
    sections = {"config": _config_section(db_path)}
    for key, (load_section, _) in FILE_SECTIONS.items():
        sections[key] = load_section(db_path)
    return {"sections": sections}


def _reevaluate_salaries(db_path: Path | str | None) -> dict[str, Any]:
    """Mesma reavaliação do set_config: as vagas abertas passam a usar a regra nova da pretensão."""
    from vagas.db import connect, default_db_path
    from vagas.salary import SalaryStore
    from vagas.salary_policy import default_policy_path

    db = Path(db_path) if db_path is not None else default_db_path()
    conn = connect(db)
    try:
        store = SalaryStore(conn, policy_path=default_policy_path(db), rule=config.resolve("salary_rule", db)[0])
        return store.reevaluate_applications()
    finally:
        conn.close()


def _validate_config(values: Any, db_path: Path | str | None) -> tuple[dict[str, str | None], dict[str, str]]:
    cleaned: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    if not isinstance(values, dict):
        return cleaned, {"config": "A seção config deve ser um objeto {chave: valor}."}
    for key, raw in values.items():
        if key not in config.SETTINGS:
            errors[f"config.{key}"] = f"Configuração desconhecida: {key!r}."
            continue
        if raw is not None and not isinstance(raw, str):
            errors[f"config.{key}"] = "Informe o valor como texto."
            continue
        try:
            cleaned[key] = config.clean(key, raw, db_path)
        except VagasError as exc:
            errors[f"config.{key}"] = str(exc)
    return cleaned, errors


def save(data: Any, db_path: Path | str | None = None) -> dict[str, Any]:
    """Valida todas as seções e só grava se não houver erro. Campos ausentes ficam como estão.

    Retorna {saved, errors: {campo: mensagem}, warnings, settings (o load() depois de gravar),
    reevaluated (só quando a regra da pretensão mudou)}."""
    result: dict[str, Any] = {"saved": False, "errors": {}, "warnings": []}
    if not isinstance(data, dict):
        result["errors"]["form"] = "Formulário inválido: envie um objeto com as seções."
        return result
    for section in data:
        if section != "config" and section not in FILE_SECTIONS:
            result["errors"][section] = f"Seção desconhecida: {section!r}."
    cleaned, errors = _validate_config(data.get("config", {}), db_path)
    result["errors"].update(errors)
    pending_files = []
    for key, (_, plan_section) in FILE_SECTIONS.items():
        if key in data:
            planned, section_errors = plan_section(data[key], db_path)
            result["errors"].update(section_errors)
            if planned is not None:
                pending_files.append((key, planned))
    if not result["errors"]:
        for key, stored in cleaned.items():
            if stored is not None:
                try:
                    config.prepare_folder(key, stored)
                except VagasError as exc:
                    result["errors"][f"config.{key}"] = str(exc)
    if result["errors"]:
        return result

    # O cofre primeiro: se o chaveiro ou a DPAPI recusar, nada mais é gravado.
    for key, planned in pending_files:
        if key == "vault":
            try:
                planned.run()
            except VagasError as exc:
                result["errors"]["vault"] = str(exc)
                return result
    rule_before = config.resolve("salary_rule", db_path)[0]
    if cleaned:
        config.write(cleaned, db_path)
    for key, planned in pending_files:  # tudo validado antes: cada arquivo é gravado de uma vez
        if key != "vault":
            md_fields.write_atomic(planned.path, planned.text)
    result["saved"] = True
    result["warnings"] = [w for key in cleaned if cleaned[key] is not None and (w := config.env_warning(key, db_path))]
    policy_changed = any(key == "policy" for key, _ in pending_files)
    if config.resolve("salary_rule", db_path)[0] != rule_before or policy_changed:
        result["reevaluated"] = _reevaluate_salaries(db_path)  # pretensões das vagas abertas com a regra nova
    result["settings"] = load(db_path)
    return result
