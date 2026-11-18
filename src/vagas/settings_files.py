"""Seções do painel que editam arquivos pessoais em Markdown: perfil para formulários e critérios de triagem.

Cada seção sabe ler o arquivo para o formulário (`load`) e preparar a gravação (`plan`), sem gravar: o
settings_form valida todas as seções antes de gravar qualquer uma. A leitura e a troca de valores ficam
em md_fields, que preserva o resto do arquivo; a validação dos critérios usa o mesmo parse_criteria da
triagem. Arquivo inexistente nasce do .example.md. Não depende de HTTP nem de MCP.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vagas import affirmative, consents, diversity, md_fields
from vagas.models import ROLE_KEYS, ROLE_NAMES, SENIORITIES, SENIORITY_LABELS
from vagas.normalize import normalize_text
from vagas.experience import DECLARED_LABEL
from vagas.profile_fields import MANUAL, OTHER_SECTION, TALENT_POOL, default_skill_dir, is_sensitive
from vagas.repo import VagasError

PENDING = "<PREENCHER>"


@dataclass
class Pending:
    """Gravação preparada: o texto novo do arquivo."""
    path: Path
    text: str


def _norm(text: str) -> str:
    return " ".join(normalize_text(text).split())


def _source(path: Path, example: Path) -> tuple[str, bool]:
    """Texto atual do arquivo e se ele ainda não existe (nesse caso, o texto é o do exemplo)."""
    if path.exists():
        return path.read_text(encoding="utf-8"), False
    if example.exists():
        return example.read_text(encoding="utf-8"), True
    raise VagasError(f"Nem {path.name} nem {example.name} foram encontrados em {path.parent}. Confira a pasta "
                     "skill/candidaturas do repositório (variável VAGAS_SKILL_DIR).")


def _error_section(key: str, title: str, message: str) -> dict[str, Any]:
    return {"key": key, "title": title, "file": "", "groups": [], "pending": [], "error": message}


# --- perfil para formulários -----------------------------------------------------------------

PROFILE_TITLE = "Perfil para formulários"
_YES = {"sim", "s", "yes"}
_NO = {"nao", "n", "no"}


# Diversidade e inclusão: um campo por pergunta (vagas.diversity). Listas fechadas (deficiência, cor/raça do IBGE)
# viram uma escolha; as demais aceitam "Outra" com texto livre. O campo "Diversidade" do formato antigo some: as
# respostas dele aparecem nos campos novos, para o usuário conferir e salvar.
MIGRATED_NOTE = "Resposta trazida do formato antigo do perfil: confira e salve para gravar."
DISABILITY_NOTE = 'Também decide a triagem: só com "Sim" as vagas exclusivas para PcD seguem.'


def _question(item: md_fields.Item) -> diversity.Question | None:
    """Pergunta de lista fechada ou com "Outra": as de diversidade e o "autorizo / não autorizo" dos consentimentos."""
    if item.parent is not None:
        return None
    if _norm(item.label) == _norm(consents.DATA):
        return consents.DATA_QUESTION
    return diversity.question(item.label)


def _old_block(items: list[md_fields.Item]) -> tuple[md_fields.Item, dict[str, dict[str, str | None]]] | None:
    """O campo "Diversidade" antigo e a proposta de cada pergunta que o perfil ainda não tem."""
    old = next((i for i in items if i.parent is None and diversity.is_old_block(i.label)), None)
    if old is None:
        return None
    children = [f"{c.label}: {c.value}" for c in items if c.parent == old.label and c.section == old.section]
    present = {i.label for i in items if i.parent is None}
    rows = diversity.proposal(children + old.notes, present)
    return old, {row["label"]: row for row in rows}


def _choice_value(q: diversity.Question, raw: str) -> str | None:
    """Valor a gravar; None se a lista é fechada e a resposta não é uma das opções."""
    text = raw.strip()
    if not text:
        return ""
    return diversity.canonical(q, text) if q.closed else text


def _pcd_in_criteria(db_path: Path | str | None) -> bool:
    from vagas.triage import parse_criteria

    try:
        path, _ = _criteria_paths(db_path)
        return "pcd" in parse_criteria(path.read_text(encoding="utf-8")).affirmative_ok
    except (OSError, VagasError):
        return False


# Idiomas: uma linha por idioma, com o nível; no arquivo continua uma linha só, "idioma (nível), ...".
LANGUAGE_LEVELS = ("Nativo", "Fluente", "Avançado", "Intermediário", "Básico", "A1", "A2", "B1", "B2", "C1", "C2")
_LEVEL_WORDS = ("nativ", "fluent", "avancad", "intermedi", "basic", "inician", "elementar")


def _split_top(text: str) -> list[str]:
    """Separa por vírgula fora de parênteses: "a (x, y), b" -> ["a (x, y)", "b"]."""
    parts, depth, current = [], 0, ""
    for char in text:
        depth += char == "("
        depth -= char == ")" and depth > 0
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [part.strip().rstrip(".") for part in parts if part.strip().rstrip(".")]


def parse_languages(value: str) -> list[dict[str, str]]:
    """"inglês intermediário-avançado (B2, certificado)" -> idioma "inglês", nível "intermediário-avançado
    (B2, certificado)"; "português (nativo)" -> "português", "nativo". O texto original fica em "raw"."""
    rows = []
    for raw in _split_top(value):
        before, _, inner = raw.partition("(")
        inner = inner.rsplit(")", 1)[0].strip()
        words = before.split()
        cut = next((i for i, w in enumerate(words) if normalize_text(w).startswith(_LEVEL_WORDS)), len(words))
        language, level_words = " ".join(words[:cut]), " ".join(words[cut:])
        level = f"{level_words} ({inner})" if level_words and inner else level_words or inner
        rows.append({"language": language or raw, "level": level, "raw": raw})
    return rows


def _languages_line(rows: list[dict[str, str]]) -> str:
    out = []
    for row in rows:
        original = next((p for p in parse_languages(row.get("raw", "")) if p["raw"] == row.get("raw")), None)
        if original and original["language"] == row["language"] and original["level"] == row["level"]:
            out.append(row["raw"])  # linha não alterada: o texto original, como foi escrito
        else:
            level = row["level"]
            out.append(f"{row['language']} ({level.lower() if level in LANGUAGE_LEVELS[:5] else level})")
    return ", ".join(out)


def _profile_paths(db_path: Path | str | None) -> tuple[Path, Path]:
    skill = default_skill_dir(db_path)
    return skill / "perfil.md", skill / "perfil.example.md"


def _hint(value: str) -> str:
    """"<PREENCHER: DD/MM/AAAA>" -> "DD/MM/AAAA"; "<...>" -> ""."""
    inner = value.strip().removeprefix("<").removesuffix(">").strip()
    inner = re.sub(r"^preencher\s*:?\s*", "", inner, flags=re.IGNORECASE)
    return "" if inner in ("", "...", "…") else inner


def _locked_status(item: md_fields.Item) -> str | None:
    """Documentos e senhas: o perfil só diz onde ficam, nunca o valor."""
    value = _norm(item.value)
    if re.match(r"(no )?cofre\b", value):
        return "No cofre: a extensão do Chrome preenche nos formulários."
    if value == _norm(MANUAL) or is_sensitive(item.label):
        return "Você digita no formulário (dado sensível não fica no perfil)."
    return None


def _profile_kind(item: md_fields.Item, items: list[md_fields.Item]) -> str:
    if _locked_status(item):
        return "locked"
    if (q := _question(item)) is not None:
        return "choice" if q.closed else "choice_other"
    if _norm(item.label) == "idiomas" and item.parent is None:
        return "languages"
    if _norm(item.label) == _norm(DECLARED_LABEL) and item.parent is None:
        return "years"
    if not item.value.strip() and any(other.parent == item.label and other.section == item.section for other in items):
        return "group"
    if any(_norm(note).startswith("valores aceitos: sim ou nao") for note in item.notes) \
            or _norm(item.label) == _norm(TALENT_POOL):
        return "yesno"
    return "text"


def _yes_no(value: str) -> str:
    word = _norm(value).rstrip(".!").split(" ")[0] if value.strip() else ""
    return "sim" if word in _YES else "não" if word in _NO else ""


def load_profile(db_path: Path | str | None) -> dict[str, Any]:
    try:
        path, example = _profile_paths(db_path)
        text, from_example = _source(path, example)
    except VagasError as exc:
        return _error_section("profile", PROFILE_TITLE, str(exc))
    items = md_fields.parse(text)
    groups: list[dict[str, Any]] = []
    pending: list[str] = []
    old = _old_block(items)
    for item in items:
        if item.label.startswith("<"):
            continue  # linha-modelo do exemplo ("<Rótulo do campo ...>"), não é campo
        if old and (item is old[0] or (item.parent == old[0].label and item.section == old[0].section)):
            continue  # diversidade no formato antigo: as respostas aparecem nos campos novos
        kind = _profile_kind(item, items)
        placeholder = item.value.strip().startswith("<")
        value = "" if placeholder else item.value.strip()
        hint = _hint(item.value) if placeholder else ""
        if from_example and kind in ("text", "yesno") and not placeholder:
            hint, value = value, ""  # o exemplo é dica, nunca valor de outra pessoa
        if kind == "yesno":
            value = _yes_no(value)
        if kind == "years":
            value = "" if _norm(item.value) in ("", "calculado") or placeholder else item.value.strip()
            hint = "Em branco: calculado pelo currículo geral"
        if kind == "languages":
            rows = parse_languages(item.value) if not placeholder else []
            value, hint = ([], "") if from_example else (rows, "")
            hint_rows = rows if from_example else []
        if kind in ("choice", "choice_other"):
            value = "" if from_example or placeholder else (diversity.canonical(_question(item), value) or "")
            hint = ""
        field = {"id": item.id, "title": item.label, "kind": kind, "value": value, "hint": hint,
                 **({"levels": list(LANGUAGE_LEVELS), "hint_rows": hint_rows} if kind == "languages" else {}),
                 **(_choices(_question(item)) if kind in ("choice", "choice_other") else {}),
                 "notes": [n for n in item.notes if not _norm(n).startswith("valores aceitos")],
                 "parent": item.parent, "status": _locked_status(item) if kind == "locked" else None}
        if kind in ("text", "yesno", "languages", "choice", "choice_other") and not value:
            pending.append(item.id)
        if not groups or groups[-1]["name"] != (item.section or ""):
            groups.append({"name": item.section or "", "fields": []})
        groups[-1]["fields"].extend(_with_periods(field, db_path) if kind == "years" else [field])
    if not from_example:
        for item, kind in _missing_from_example(items, example):
            field = {"id": item.id, "title": item.label, "kind": kind, "value": "", "missing": True,
                     "hint": _hint(item.value) if item.value.strip().startswith("<") else item.value.strip(),
                     "notes": [n for n in item.notes if not _norm(n).startswith("valores aceitos")],
                     "parent": None, "status": None}
            if kind in ("choice", "choice_other"):
                field.update(_choices(_question(item)), hint="")
                proposed = old[1].get(item.label) if old else None
                if proposed and proposed["value"]:
                    field.update(value=proposed["value"], migrated=True)
                    field["notes"] = [*field["notes"], MIGRATED_NOTE]
            group = next((g for g in groups if g["name"] == (item.section or "")), None)
            if group is None:
                group = {"name": item.section or "", "fields": []}
                groups.append(group)
            group["fields"].extend(_with_periods(field, db_path) if kind == "years" else [field])
    _disability_notes(groups, db_path)
    return {"key": "profile", "title": PROFILE_TITLE, "file": str(path), "new": from_example,
            "groups": groups, "pending": pending}


def _choices(q: diversity.Question) -> dict[str, Any]:
    options = [*q.options, diversity.NOT_SAY] if q.not_say else list(q.options)
    if q.closed:
        return {"choices": [{"value": "", "label": "Escolha…"}, *({"value": o, "label": o} for o in options)]}
    return {"choices": options}


def _disability_notes(groups: list[dict[str, Any]], db_path: Path | str | None) -> None:
    """Possui deficiência: como decide a triagem e, se os critérios disserem outra coisa, o aviso."""
    for group in groups:
        for field in group["fields"]:
            if field["title"] != diversity.DISABILITY or field["parent"] is not None:
                continue
            field["notes"] = [*field["notes"], DISABILITY_NOTE]
            if field["value"] != "Sim" and _pcd_in_criteria(db_path):
                field["notes"].append('Os critérios de triagem incluem PcD em "Vagas afirmativas que posso disputar", '
                                      'mas vale esta resposta: sem "Sim", as vagas exclusivas para PcD são descartadas.')


def _periods_field(db_path: Path | str | None) -> dict[str, Any]:
    """Experiências do currículo geral aprovado (só leitura no perfil) e os anos somados."""
    from datetime import date

    from vagas.db import connect
    from vagas.experience import experience_years
    from vagas.resume_repo import ResumeStore, default_draft_path

    conn = connect(db_path) if db_path is not None else connect()
    try:
        master = ResumeStore(conn, default_draft_path(db_path)).get_master_resume()["resume"]
    except VagasError:
        master = None
    finally:
        conn.close()
    exact = experience_years(master, date.today()) if master else None
    return {"id": "__periods__", "title": "Experiências do currículo geral", "kind": "periods",
            "value": [{k: item.get(k, "") for k in ("company", "title", "start", "end")}
                      for item in (master or {}).get("experience", [])],
            "years_exact": exact, "years_computed": int(exact + 0.5) if exact is not None else None,
            "hint": "", "parent": None, "status": None,
            "notes": ["Edite as experiências na seção Currículo geral." if master
                      else "Ainda não há currículo geral aprovado: os anos não podem ser calculados."]}


def _with_periods(field: dict[str, Any], db_path: Path | str | None) -> list[dict[str, Any]]:
    periods = _periods_field(db_path)
    if periods["years_computed"] is not None:
        field["hint"] = f"Em branco: {periods['years_computed']} anos, calculados pelo currículo geral"
    return [periods, field]


def _years_value(raw: str) -> str | None:
    """Vazio -> "calculado"; número -> o número; outro texto -> None (inválido)."""
    text = raw.strip()
    if not text or _norm(text) == "calculado":
        return "calculado"
    return text if re.fullmatch(r"\d{1,2}(?:[.,]\d)?", text) else None


YEARS_ERROR = "Informe um número de anos, ou deixe em branco para usar o calculado."


def _missing_from_example(items: list[md_fields.Item], example: Path) -> list[tuple[md_fields.Item, str]]:
    """Campos de primeiro nível do exemplo que o perfil ainda não tem (ex.: um campo novo numa versão
    nova). Aparecem vazios no painel e só entram no arquivo quando preenchidos."""
    if not example.exists():
        return []
    have = {md_fields._key(item.id) for item in items}
    have_labels = {_norm(item.label) for item in items}
    example_items = md_fields.parse(example.read_text(encoding="utf-8"))
    missing = []
    for item in example_items:
        if item.parent or item.label.startswith("<") or diversity.is_old_block(item.label):
            continue
        if md_fields._key(item.id) in have or _norm(item.label) in have_labels:
            continue
        kind = _profile_kind(item, example_items)
        if kind in ("text", "yesno", "years", "choice", "choice_other"):
            missing.append((item, kind))
    return missing


def _check_languages(raw: Any, name: str) -> tuple[str, dict[str, str]]:
    if not isinstance(raw, list):
        return "", {name: "Envie os idiomas como uma lista."}
    errors, rows = {}, []
    for index, row in enumerate(raw):
        where = f"{name}.{index}"
        if not isinstance(row, dict):
            errors[where] = "Linha inválida."
            continue
        language = str(row.get("language") or "").strip()
        level = str(row.get("level") or "").strip()
        if not language:
            errors[f"{where}.language"] = "Informe o idioma."
        elif re.search(r"[,()\n\r]", language):
            errors[f"{where}.language"] = "O idioma não pode ter vírgula, parênteses nem quebra de linha."
        if not level:
            errors[f"{where}.level"] = "Escolha o nível."
        elif re.search(r"[\n\r]", level) or level.count("(") != level.count(")"):
            errors[f"{where}.level"] = "Use uma linha só, com os parênteses fechados."
        rows.append({"language": language, "level": level, "raw": str(row.get("raw") or "")})
    return ("" if errors else _languages_line(rows)), errors


def plan_profile(values: Any, db_path: Path | str | None) -> tuple[Pending | None, dict[str, str]]:
    if not isinstance(values, dict):
        return None, {"profile": "A seção profile deve ser um objeto {campo: valor}."}
    try:
        path, example = _profile_paths(db_path)
        text, from_example = _source(path, example)
    except VagasError as exc:
        return None, {"profile": str(exc)}
    items = md_fields.parse(text)
    by_key = {md_fields._key(item.id): item for item in items}
    missing = {} if from_example else {md_fields._key(i.id): (i, kind) for i, kind in _missing_from_example(items, example)}
    inserts: list[tuple[str | None, str]] = []
    old = None if from_example else _old_block(items)
    diversity_answers: dict[str, tuple[str | None, str]] = {}  # campos novos de diversidade: rótulo -> (seção, valor)
    updates: dict[str, str] = {}
    errors: dict[str, str] = {}
    for field_id, raw in values.items():
        name = f"profile.{field_id}"
        if (new := missing.get(md_fields._key(str(field_id)))) is not None:
            new_item, new_kind = new
            if not isinstance(raw, str) or "\n" in raw or "\r" in raw or raw.strip().startswith("<"):
                errors[name] = "Informe o valor numa linha só (sem começar com '<')."
            elif new_kind in ("choice", "choice_other"):
                q = _question(new_item)
                if (chosen := _choice_value(q, raw)) is None:
                    errors[name] = _choice_error(q)
                elif diversity.question(new_item.label) is not None:
                    diversity_answers[new_item.label] = (new_item.section, chosen)
                elif chosen:  # vazio: o campo continua fora do arquivo
                    inserts.append((new_item.section, f"- {new_item.label}: {chosen}"))
            elif new_kind == "yesno" and raw.strip() and not _yes_no(raw):
                errors[name] = "Responda sim ou não."
            elif new_kind == "years" and _years_value(raw) is None:
                errors[name] = YEARS_ERROR
            elif new_kind == "years":
                inserts.append((new_item.section, f"- {new_item.label}: {_years_value(raw)}"))
            elif raw.strip():  # vazio: o campo continua fora do arquivo
                value = _yes_no(raw) if new_kind == "yesno" else raw.strip()
                inserts.append((new_item.section, f"- {new_item.label}: {value}"))
            continue
        item = by_key.get(md_fields._key(str(field_id)))
        if item is None:
            errors[name] = "Campo desconhecido no perfil."
            continue
        kind = _profile_kind(item, items)
        if kind == "years":
            stored = _years_value(raw) if isinstance(raw, str) else None
            if stored is None:
                errors[name] = YEARS_ERROR
            else:
                updates[item.id] = stored
            continue
        if kind == "languages":
            line, row_errors = _check_languages(raw, name)
            errors.update(row_errors)
            if not row_errors:
                updates[item.id] = line or PENDING
            continue
        if kind in ("choice", "choice_other") and isinstance(raw, str) and "\n" not in raw and "\r" not in raw:
            if (chosen := _choice_value(_question(item), raw)) is None:
                errors[name] = _choice_error(_question(item))
            else:
                updates[item.id] = chosen or PENDING
            continue
        if not isinstance(raw, str):
            errors[name] = "Informe o valor como texto."
        elif kind == "locked":
            errors[name] = ("Documentos e senhas não ficam no perfil. CPF, RG e similares vão para o cofre (seção "
                            "Documentos do cofre); senhas você digita no formulário.")
        elif kind == "group":
            errors[name] = "Este item só agrupa os campos abaixo dele."
        elif "\n" in raw or "\r" in raw:
            errors[name] = "Use uma linha só."
        elif raw.strip().startswith("<"):
            errors[name] = "O valor não pode começar com '<' (é a marca de campo a preencher)."
        elif kind == "yesno" and raw.strip() and not _yes_no(raw):
            errors[name] = "Responda sim ou não."
        else:
            value = _yes_no(raw) if kind == "yesno" else raw.strip()
            updates[item.id] = value or PENDING
    if errors:
        return None, errors
    if from_example:  # perfil novo: o que não foi digitado fica pendente, nunca com o valor do exemplo
        for item in items:
            if item.id not in updates and _profile_kind(item, items) in ("text", "yesno", "languages", "choice",
                                                                           "choice_other") \
                    and not item.value.strip().startswith("<"):
                updates[item.id] = PENDING
    if not updates and not diversity_answers and not inserts:
        return None, {}
    new_text = md_fields.apply(text, updates)
    for section, line in inserts:
        new_text = md_fields.insert_item(new_text, section, line, before=OTHER_SECTION)
    if diversity_answers:
        new_text = _write_diversity(new_text, diversity_answers, old, missing)
    return Pending(path, new_text), {}


def _choice_error(q: diversity.Question) -> str:
    if q.closed:
        options = [c["value"] for c in _choices(q)["choices"] if c["value"]]
        return f"Escolha uma das opções: {', '.join(options)}."
    return "Escolha uma opção ou escreva a resposta numa linha só."


def _write_diversity(text: str, answers: dict[str, tuple[str | None, str]], old: Any,
                     missing: dict[str, tuple[md_fields.Item, str]]) -> str:
    """Grava os campos novos de diversidade. Com o campo antigo no perfil, grava todas as perguntas que faltam
    (a resposta enviada, senão a trazida do formato antigo, senão a preencher) e tira o campo antigo."""
    rows = dict(answers)
    if old is not None:
        for item, kind in missing.values():
            if diversity.question(item.label) is not None and item.label not in rows:
                proposed = old[1].get(item.label) or {}
                rows[item.label] = (item.section, proposed.get("value") or "")
        text = md_fields.remove_item(text, old[0].id)
    order = [q.label for q in diversity.QUESTIONS]
    for label in sorted(rows, key=lambda lb: order.index(lb) if lb in order else len(order)):
        section, value = rows[label]
        if value or old is not None:
            text = md_fields.insert_item(text, section, f"- {label}: {value or PENDING}", before=OTHER_SECTION)
    return text


# --- critérios de triagem --------------------------------------------------------------------

CRITERIA_TITLE = "Critérios de triagem"


def _criteria_paths(db_path: Path | str | None) -> tuple[Path, Path]:
    from vagas.triage import default_criteria_path

    path = default_criteria_path(db_path)
    example = path.resolve().parent / "criterios-triagem.example.md"
    if not example.exists():
        try:
            example = default_skill_dir(db_path) / "criterios-triagem.example.md"
        except VagasError:
            pass
    return path, example


def _criteria_field(label: str) -> str | None:
    from vagas.triage import _KEYS

    return _KEYS.get(normalize_text(label).strip())


def _affirmative_label(key: str) -> str:
    return affirmative.GROUPS[key].label[0].upper() + affirmative.GROUPS[key].label[1:]


# Campos dos critérios que o painel não mostra: os termos de vaga exclusiva PcD são conhecimento da
# ferramenta (triage.DEFAULT_PCD_TERMS); uma linha antiga no arquivo continua valendo.
HIDDEN_CRITERIA = {"pcd_terms", "accepted_states"}  # os estados aceitos ficam nos grupos de locais
PLACES_LABEL = "Locais aceitos para híbrido e presencial"

_MULTI = {
    "target_roles": lambda: [{"value": k, "label": ROLE_NAMES[k][0].capitalize()} for k in ROLE_KEYS if k in ROLE_NAMES],
    "conditional_roles": lambda: [{"value": k, "label": ROLE_NAMES[k][0].capitalize()} for k in ROLE_KEYS
                                  if k in ROLE_NAMES],
    "search_seniorities": lambda: [{"value": k, "label": SENIORITY_LABELS.get(k, k).capitalize()} for k in SENIORITIES],
    "affirmative_ok": lambda: [{"value": k, "label": _affirmative_label(k)} for k in affirmative.GROUPS],
}
_HELP = {
    "target_roles": "Cargos que seguem na triagem.",
    "conditional_roles": "Cargos que só seguem com aderência igual ou maior que a mínima.",
    "min_match": "De 0 a 100: quanto da vaga precisa bater com o seu currículo geral.",
    "ignored_companies": "Separadas por vírgula. Maiúsculas, acentos, Ltda e S.A. são ignorados.",
    "affirmative_ok": ("Grupos cujas vagas afirmativas você quer disputar. Nenhum marcado: nenhuma. PcD: com "
                       "\"Possui deficiência\" preenchido no perfil, é ele que decide."),
    "accepted_locations": ("Cidades aceitas para vagas híbridas e presenciais, por estado. Vaga em estado fora da "
                           "lista é descartada; num estado da lista mas em outra cidade, você julga. Remotas são "
                           "sempre aceitas."),
    "search_seniorities": "Níveis a que você se candidata. Nenhum marcado: todos.",
    "years_by_level": "Faixa de anos de cada nível, como \"pleno 2-5\", separadas por vírgula.",
    "accepted_states": "Siglas ou nomes de estados, separados por vírgula. Vazio: não filtra por estado.",
}


def _items_of(value: str) -> list[str]:
    return [part.strip().rstrip(".") for part in value.split(",") if part.strip().rstrip(".")]


def _as_choices(field: str, value: str) -> list[str]:
    from vagas.triage import _roles

    items = _items_of(value)
    if field in ("target_roles", "conditional_roles"):
        return list(_roles(items, "critérios"))
    if field == "search_seniorities":
        levels = [normalize_text(v) for v in items]
        unknown = [v for v, level in zip(items, levels) if level not in SENIORITIES]
        if unknown:
            raise VagasError(f"Senioridade desconhecida: {', '.join(unknown)}.")
        return list(dict.fromkeys(levels))
    return list(affirmative.parse_groups(items, "critérios"))


def _as_line_value(field: str, chosen: list[str]) -> str:
    if field == "affirmative_ok":
        return ", ".join(affirmative.GROUPS[k].aliases[0] for k in chosen) or "nenhuma"
    return ", ".join(chosen)


def _state_choices() -> list[dict[str, str]]:
    from vagas.places import STATES

    return [{"value": uf, "label": f"{uf} — {name}"} for uf, name in STATES.items()]


def _places_of(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Grupos de locais aceitos ({state, cities}; state "" = qualquer estado) e se vieram da linha antiga
    "Estados aceitos", que some ao salvar. Com um estado só nela, as cidades sem estado passam a ser dele."""
    from vagas.places import parse_places, state_code

    items = {_criteria_field(i.label): i for i in md_fields.parse(text) if not i.parent}
    raw = items["accepted_locations"].value.strip() if "accepted_locations" in items else ""
    groups = [{"state": g.state or "", "cities": list(g.cities)}
              for g in parse_places("" if raw.startswith("<") else raw, PLACES_LABEL)]
    old = items.get("accepted_states")
    legacy = []
    for value in _items_of(old.value if old and not old.value.strip().startswith("<") else ""):
        if (uf := state_code(value)) is None:
            raise VagasError(f"Estado desconhecido em 'Estados aceitos para híbrido e presencial': {value!r}.")
        legacy.append(uf)
    if not legacy:
        return groups, False
    states = list(dict.fromkeys([g["state"] for g in groups if g["state"]] + legacy))
    loose = next((g for g in groups if not g["state"]), None)
    if loose and len(states) == 1:
        own = next((g for g in groups if g["state"] == states[0]), None)
        if own:
            own["cities"] = list(dict.fromkeys(loose["cities"] + own["cities"]))
            groups.remove(loose)
        else:
            loose["state"] = states[0]
    groups += [{"state": uf, "cities": []} for uf in states if not any(g["state"] == uf for g in groups)]
    return groups, True


def _places_field(text: str, item_id: str) -> dict[str, Any]:
    field: dict[str, Any] = {"id": item_id, "title": PLACES_LABEL, "help": _HELP["accepted_locations"],
                             "kind": "places", "value": [], "states": _state_choices(), "hint": "", "notes": [],
                             "parent": None, "status": None}
    try:
        field["value"], field["migrated"] = _places_of(text)
    except VagasError as exc:
        field["error"] = f"{exc} Corrija o arquivo ou cadastre os locais de novo."
    return field


def accepted_places(db_path: Path | str | None) -> list[dict[str, Any]]:
    """Grupos de locais aceitos dos critérios, como o painel os mostra; [] se não der para ler."""
    try:
        return _places_of(_source(*_criteria_paths(db_path))[0])[0]
    except VagasError:
        return []


def _check_places(raw: Any) -> tuple[str | None, str | None]:
    """Valor da linha de locais ("SP: São Carlos, Barueri; MG:") a partir dos grupos do painel, ou o erro."""
    from vagas.places import PlaceGroup, format_places, state_code

    if not isinstance(raw, list) or not all(isinstance(g, dict) for g in raw):
        return None, "Envie os locais como uma lista de grupos {state, cities}."
    groups: list[PlaceGroup] = []
    for group in raw:
        state, cities = group.get("state") or "", group.get("cities") or []
        if not isinstance(state, str) or not isinstance(cities, list) or not all(isinstance(c, str) for c in cities):
            return None, "Cada grupo precisa de um estado e de uma lista de cidades."
        names = list(dict.fromkeys(c.strip().rstrip(".").strip() for c in cities if c.strip().rstrip(".").strip()))
        if any(re.search(r"[,;:\n\r]", c) for c in names):
            return None, "Uma cidade por item, sem vírgula, ponto e vírgula ou dois-pontos."
        uf = state_code(state) if state.strip() else None
        if state.strip() and uf is None:
            return None, f"Estado desconhecido: {state!r}. Escolha um estado da lista."
        if uf is None and not names:
            continue  # grupo vazio, sem estado: nada a gravar
        if any(g.state == uf for g in groups):
            return None, f"O estado {uf or 'sem estado'} aparece duas vezes: junte as cidades num grupo só."
        groups.append(PlaceGroup(uf, tuple(names)))
    return format_places(groups), None


def load_criteria(db_path: Path | str | None) -> dict[str, Any]:
    try:
        path, example = _criteria_paths(db_path)
        text, from_example = _source(path, example)
    except VagasError as exc:
        return _error_section("criteria", CRITERIA_TITLE, str(exc))
    fields = []
    has_places = False
    for item in md_fields.parse(text):
        name = _criteria_field(item.label)
        if name is None or item.parent or name in HIDDEN_CRITERIA:
            continue
        if name == "accepted_locations":
            fields.append(_places_field(text, item.id))
            has_places = True
            continue
        raw = item.value.strip()
        field: dict[str, Any] = {"id": item.id, "title": item.label, "help": _HELP.get(name, ""), "kind": "text",
                                 "value": "" if raw.startswith("<") else raw, "hint": _hint(raw) if raw.startswith("<")
                                 else "", "notes": [], "parent": None, "status": None}
        if name in _MULTI:
            field["choices"] = _MULTI[name]()
            try:
                field.update(kind="multi", value=_as_choices(name, raw))
            except VagasError as exc:
                field["error"] = f"{exc} Corrija o texto ou escolha de novo."
        elif name == "min_match":
            field.update(kind="int", bounds=[0, 100], value=raw.rstrip("%").strip())
        fields.append(field)
    if not has_places:  # arquivo sem a linha: o campo aparece mesmo assim e a linha é criada ao salvar
        fields.append(_places_field(text, PLACES_LABEL))
    return {"key": "criteria", "title": CRITERIA_TITLE, "file": str(path), "new": from_example,
            "groups": [{"name": "", "fields": fields}], "pending": [] if not from_example else ["criteria"]}


def _check(label: str, value: str, field: str) -> str | None:
    """Erro de um campo, validado sozinho pelo mesmo parse_criteria da triagem."""
    from vagas.triage import parse_criteria

    lines = [f"- {label}: {value}"]
    if field != "target_roles":
        lines.insert(0, "- Cargos alvo: data_scientist")
    try:
        parse_criteria("\n".join(lines) + "\n", source=f"'{label}'")
    except VagasError as exc:
        return re.sub(r" em '[^']*', linha \d+", "", str(exc))
    return None


def plan_criteria(values: Any, db_path: Path | str | None) -> tuple[Pending | None, dict[str, str]]:
    from vagas.triage import parse_criteria

    if not isinstance(values, dict):
        return None, {"criteria": "A seção criteria deve ser um objeto {campo: valor}."}
    try:
        path, example = _criteria_paths(db_path)
        text, _ = _source(path, example)
    except VagasError as exc:
        return None, {"criteria": str(exc)}
    by_key = {md_fields._key(item.id): item for item in md_fields.parse(text) if not item.parent}
    updates: dict[str, str] = {}
    errors: dict[str, str] = {}
    places: str | None = None
    for field_id, raw in values.items():
        name = f"criteria.{field_id}"
        if _criteria_field(str(field_id)) == "accepted_locations":
            places, problem = _check_places(raw)
            if problem:
                errors[name] = problem
            continue
        item = by_key.get(md_fields._key(str(field_id)))
        field = _criteria_field(item.label) if item else None
        if field is None or field in HIDDEN_CRITERIA:
            errors[name] = "Campo desconhecido nos critérios."
            continue
        if field in _MULTI:
            valid = {c["value"] for c in _MULTI[field]()}
            if not isinstance(raw, list) or not all(isinstance(v, str) and v in valid for v in raw):
                errors[name] = "Escolha entre as opções da lista."
                continue
            value = _as_line_value(field, list(dict.fromkeys(raw)))
        elif not isinstance(raw, str) or "\n" in raw or "\r" in raw:
            errors[name] = "Informe o valor como texto, numa linha só."
            continue
        else:
            value = raw.strip()
        if problem := _check(item.label, value, field):
            errors[name] = problem
            continue
        updates[item.id] = value
    if errors:
        return None, errors
    if not updates and places is None:
        return None, {}
    new_text = md_fields.apply(text, updates)
    if places is not None:
        new_text = _write_places(new_text, places)
    try:
        parse_criteria(new_text, source=path.name)
    except VagasError as exc:
        return None, {"criteria": str(exc)}
    return Pending(path, new_text), {}


def _write_places(text: str, value: str) -> str:
    """Grava a linha de locais (criando-a se faltar) e tira a linha antiga "Estados aceitos"."""
    items = {_criteria_field(i.label): i for i in md_fields.parse(text) if not i.parent}
    if "accepted_locations" in items:
        text = md_fields.apply(text, {items["accepted_locations"].id: value})
    else:
        text = md_fields.insert_item(text, None, f"- {PLACES_LABEL}: {value}".rstrip())
    if "accepted_states" in items:
        text = md_fields.remove_item(text, items["accepted_states"].id)
    return text


# --- política salarial -------------------------------------------------------------------------

POLICY_TITLE = "Política salarial"
_MODE_LABELS = {"minimo": "Mínimo", "faixa": "Faixa"}
_BAND_LINE = re.compile(r"^(?P<label>.+?)\s*\((?P<tags>[^)]*)\)$")
# Cidades da faixa: o que vem depois de "em" no nome, como o evaluate_salary lê ("e região" é ignorado).
_BAND_CITIES = re.compile(r"^(?P<name>.*?)\s*\bem\s+(?P<cities>.+?)(?:\s+e\s+regi[aã]o)?$", re.IGNORECASE)


def _split_band_label(label: str) -> tuple[str, list[str]]:
    """"Híbrido/presencial em São Paulo, Barueri e região" -> ("Híbrido/presencial", ["São Paulo", "Barueri"])."""
    match = _BAND_CITIES.match(label.strip())
    if not match:
        return label.strip(), []
    cities = [c.strip() for c in re.split(r",\s*|\s+e\s+", match["cities"]) if c.strip()]
    return match["name"].strip(), list(dict.fromkeys(cities))


def _band_label(name: str, cities: list[str]) -> str:
    return f"{name} em {', '.join(cities)}" if cities else name


def _policy_paths(db_path: Path | str | None) -> tuple[Path, Path]:
    from vagas.salary_policy import default_policy_path

    path = default_policy_path(db_path)
    example = path.resolve().parent / "politica-salarial.example.md"
    if not example.exists():
        try:
            example = default_skill_dir(db_path) / "politica-salarial.example.md"
        except VagasError:
            pass
    return path, example


def _band_items(text: str) -> list[tuple[md_fields.Item, dict[str, Any]]]:
    """Linhas de faixa ("- Nome (BRL, CLT): mínimo 8.000, máximo 12.000") como linhas da tabela."""
    from vagas.models import CURRENCIES
    from vagas.salary_policy import _ALIAS, _MAX, _MIN

    rows = []
    for item in md_fields.parse(text):
        key = _BAND_LINE.match(item.label)
        if item.parent or not key:
            continue
        tags = [t.strip().upper() for t in key["tags"].split(",")]
        currency = next((t for t in tags if t in CURRENCIES), None)
        if currency is None:
            continue
        alias, lo, hi = _ALIAS.search(item.value), _MIN.search(item.value), _MAX.search(item.value)
        name, cities = _split_band_label(key["label"])
        rows.append((item, {"name": name, "cities": cities, "currency": currency, "clt": "CLT" in tags,
                            "min": _number_text(lo["n"]) if lo and not alias else "",
                            "max": _number_text(hi["n"]) if hi and not alias else "",
                            "alias": alias["target"].strip() if alias else ""}))
    return rows


def _number_text(raw: str) -> str:
    """"8.000" -> "8000"; "10.500,50" -> "10500.5"; texto inválido volta como está."""
    from vagas.salary_policy import parse_number

    cleaned = re.sub(r"^\s*R?\$\s*", "", raw or "").strip()
    try:
        number = parse_number(cleaned)
    except VagasError:
        return raw.strip()
    return str(int(number)) if number == int(number) else f"{number:g}"


def _applies(name: str) -> str:
    """Para que vagas a faixa vale, lido do nome como o evaluate_salary lê."""
    norm = normalize_text(name)
    modes = [label for word, label in (("remoto", "remotas"), ("hibrido", "híbridas"), ("presencial", "presenciais"))
             if word in norm] or ["remotas", "híbridas", "presenciais"]
    city = re.search(r"\bem\s+(.+?)(?:\s+e\s+regi[aã]o)?$", name.strip(), flags=re.IGNORECASE)
    where = f"em {city.group(1)}" if city else "em qualquer local"
    joined = modes[0] if len(modes) == 1 else f"{', '.join(modes[:-1])} e {modes[-1]}"
    return f"Vale para vagas {joined} {where}."


def load_policy(db_path: Path | str | None) -> dict[str, Any]:
    from vagas.models import CURRENCIES, SALARY_MODES

    try:
        path, example = _policy_paths(db_path)
        text, from_example = _source(path, example)
    except VagasError as exc:
        return _error_section("policy", POLICY_TITLE, str(exc))
    fields: list[dict[str, Any]] = []
    for item in md_fields.parse(text):
        if item.parent:
            continue
        norm = _norm(item.label)
        if norm == "modo":
            fields.append({"id": item.id, "title": "Modo", "kind": "choice", "value": _norm(item.value).split(" ")[0],
                           "choices": [{"value": m, "label": _MODE_LABELS.get(m, m)} for m in SALARY_MODES],
                           "hint": "", "notes": [], "parent": None, "status": None,
                           "help": "Mínimo: aplica se a mediana de mercado for maior ou igual ao mínimo da faixa "
                                   "(o máximo só limita a pretensão). Faixa: aplica só se a mediana estiver dentro "
                                   "da faixa; acima do máximo, a vaga é descartada."})
        elif norm == "multiplicador pj":
            fields.append({"id": item.id, "title": "Multiplicador PJ", "kind": "text",
                           "value": "" if item.value.startswith("<") else item.value.strip(), "hint": "1.4",
                           "notes": [], "parent": None, "status": None,
                           "help": "Converte as faixas marcadas como CLT para vagas PJ (ex.: 1.4 = 40% a mais)."})
    rows = []
    for _, row in _band_items(text):
        row["applies"] = _applies(_band_label(row["name"], row["cities"]))
        row["hint_min"], row["hint_max"] = row["min"], row["max"]
        if from_example:
            row["min"] = row["max"] = ""  # salário é pessoal: o exemplo só sugere as faixas
        rows.append(row)
    fields.append({"id": "Faixas", "title": "Faixas", "kind": "bands", "value": rows, "currencies": list(CURRENCIES),
                   "places": accepted_places(db_path), "hint": "", "notes": [], "parent": None, "status": None,
                   "help": "Valores mensais. A faixa vale para as modalidades citadas no nome (remoto, híbrido, "
                           "presencial; nenhuma = todas) e para as cidades marcadas, escolhidas entre os locais "
                           "aceitos dos critérios (nenhuma = qualquer local). Moedas nunca são convertidas entre si."})
    pending = ["Faixas"] if from_example or not rows else []
    return {"key": "policy", "title": POLICY_TITLE, "file": str(path), "new": from_example,
            "groups": [{"name": "", "fields": fields}], "pending": pending}


def _band_line(row: dict[str, Any]) -> str:
    tags = row["currency"] + (", CLT" if row["clt"] else "")
    label = _band_label(row["name"], row["cities"])
    if row["alias"]:
        return f"- {label} ({tags}): usar a faixa do {row['alias']}"
    value = f"mínimo {_number_text(row['min'])}"
    if row["max"].strip():
        value += f", máximo {_number_text(row['max'])}"
    return f"- {label} ({tags}): {value}"


def _same_band(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """A faixa voltou do painel como foi carregada (as cidades em qualquer ordem)."""
    keys = ("name", "currency", "clt", "min", "max", "alias")
    return (all(a[k] == b[k] for k in keys)
            and sorted(normalize_text(c) for c in a["cities"]) == sorted(normalize_text(c) for c in b["cities"]))


def _check_bands(rows: Any, mode: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    from vagas.models import CURRENCIES
    from vagas.salary_policy import parse_number

    if not isinstance(rows, list):
        return [], {"policy.Faixas": "Envie as faixas como uma lista."}
    if not rows:
        return [], {"policy.Faixas": "Cadastre pelo menos uma faixa."}
    clean, errors = [], {}
    cities_of = [_row_cities(r) for r in rows]
    names = [normalize_text(_band_label(str(r.get("name", "")).strip(), cities_of[i] or []))
             if isinstance(r, dict) else "" for i, r in enumerate(rows)]
    for index, row in enumerate(rows):
        where = f"policy.Faixas.{index}"
        if not isinstance(row, dict):
            errors[where] = "Faixa inválida."
            continue
        text = {k: str(row.get(k, "") or "").strip() for k in ("name", "currency", "min", "max", "alias")}
        cities = cities_of[index]
        if any("\n" in v or "\r" in v for v in text.values()):
            errors[where] = "Use uma linha só em cada campo."
            continue
        if cities is None:
            errors[f"{where}.cities"] = "Uma cidade por item, sem vírgula, ponto e vírgula ou dois-pontos."
            cities = []
        if not text["name"]:
            errors[f"{where}.name"] = "Dê um nome à faixa (ex.: Remoto nacional)."
        elif re.search(r"[():;]", text["name"]):
            errors[f"{where}.name"] = "O nome não pode ter parênteses, dois-pontos nem ponto e vírgula."
        elif cities and _split_band_label(text["name"])[1]:
            errors[f"{where}.name"] = "Tire o \"em …\" do nome: as cidades da faixa são as marcadas abaixo."
        elif names[index] in names[:index]:
            errors[f"{where}.name"] = "Já existe uma faixa com este nome e estas cidades."
        if text["currency"].upper() not in CURRENCIES:
            errors[f"{where}.currency"] = f"Escolha a moeda: {', '.join(CURRENCIES)}."
        numbers = {}
        for key in ("min", "max"):
            if text[key] and not text["alias"]:
                try:
                    numbers[key] = parse_number(re.sub(r"^\s*R?\$\s*", "", text[key]))
                    if numbers[key] <= 0:
                        raise VagasError("")
                except VagasError:
                    errors[f"{where}.{key}"] = "Informe um valor mensal, como 8000 ou 8.000."
        if text["alias"]:
            target = normalize_text(text["alias"])
            if not any(n and n != names[index] and (n.startswith(target) or target.startswith(n)) for n in names):
                errors[f"{where}.alias"] = "Escolha outra faixa desta lista."
        elif not text["min"]:
            errors[f"{where}.min"] = "Informe o mínimo (ou use a faixa de outra)."
        if "min" in numbers and "max" in numbers and numbers["max"] < numbers["min"]:
            errors[f"{where}.max"] = "O máximo não pode ser menor que o mínimo."
        if mode == "faixa" and not text["alias"] and not text["max"]:
            errors[f"{where}.max"] = "No modo faixa, toda faixa precisa de máximo."
        clean.append({**text, "cities": cities, "currency": text["currency"].upper(), "clt": bool(row.get("clt"))})
    return clean, errors


def _row_cities(row: Any) -> list[str] | None:
    """Cidades de uma faixa vinda do painel (sem a chave: as do nome, como antes); None se inválidas."""
    if not isinstance(row, dict):
        return []
    cities = row.get("cities", [])
    if not isinstance(cities, list) or not all(isinstance(c, str) for c in cities):
        return None
    names = [c.strip() for c in cities if c.strip()]
    if any(re.search(r"[,;:()\n\r]", c) for c in names):
        return None
    return list(dict.fromkeys(names))


def plan_policy(values: Any, db_path: Path | str | None) -> tuple[Pending | None, dict[str, str]]:
    from vagas.salary_policy import parse_number, parse_policy

    if not isinstance(values, dict):
        return None, {"policy": "A seção policy deve ser um objeto {campo: valor}."}
    try:
        path, example = _policy_paths(db_path)
        text, from_example = _source(path, example)
    except VagasError as exc:
        return None, {"policy": str(exc)}
    items = {_norm(i.label): i for i in md_fields.parse(text) if not i.parent}
    errors: dict[str, str] = {}
    updates: dict[str, str] = {}
    for field_id, raw in values.items():
        if field_id == "Faixas":
            continue
        norm = _norm(str(field_id))
        if norm not in ("modo", "multiplicador pj") or norm not in items:
            errors[f"policy.{field_id}"] = "Campo desconhecido na política salarial."
        elif not isinstance(raw, str):
            errors[f"policy.{field_id}"] = "Informe o valor como texto."
        elif norm == "modo" and _norm(raw) not in _MODE_LABELS:
            errors[f"policy.{field_id}"] = "Escolha minimo ou faixa."
        elif norm == "multiplicador pj":
            try:
                if parse_number(raw) <= 0:
                    raise VagasError("")
                updates[items[norm].id] = raw.strip()
            except VagasError:
                errors[f"policy.{field_id}"] = "Informe um número maior que zero, como 1.4."
        else:
            updates[items[norm].id] = _norm(raw)
    mode = _norm(values.get("Modo", "")) if isinstance(values.get("Modo"), str) else ""
    mode = mode or (_norm(items["modo"].value).split(" ")[0] if "modo" in items else "minimo")
    current = _band_items(text)
    current_rows = [row for _, row in current]
    if from_example and "Faixas" not in values:
        return None, {**errors, "policy.Faixas": "Preencha os valores das faixas."}
    rows, band_errors = _check_bands(values.get("Faixas", current_rows), mode)
    errors.update(band_errors)
    if errors:
        return None, errors
    new_text = md_fields.apply(text, updates)
    if "Faixas" in values or from_example:
        lines = text.splitlines()
        kept = {}  # faixa sem mudança: a linha fica como estava (grafia dos números, "e região")
        for item, old in current:
            kept.setdefault(json.dumps(old, sort_keys=True), lines[item.line].rstrip())
        band_lines = []
        for row in rows:
            same = next((key for key, line in kept.items() if _same_band(json.loads(key), row)), None)
            band_lines.append(kept.pop(same) if same and not from_example else _band_line(row))
        new_text = _replace_bands(new_text, band_lines)
    try:
        parse_policy(new_text, source=path.name)
    except VagasError as exc:
        return None, {"policy": str(exc)}
    if new_text == text and not from_example:
        return None, {}
    return Pending(path, new_text), {}


def _replace_bands(text: str, band_lines: list[str]) -> str:
    """Troca as linhas de faixa pelas novas, no lugar da primeira (ou depois do multiplicador)."""
    old = [item.line for item, _ in _band_items(text)]
    lines = text.splitlines(keepends=True)
    if old:
        anchor = old[0]
    else:
        last = [i.line for i in md_fields.parse(text) if not i.parent]
        anchor = (max(last) + 1) if last else len(lines)
    kept = [line for number, line in enumerate(lines) if number not in old]
    position = anchor - sum(1 for number in old if number < anchor)
    return "".join(kept[:position] + [line + "\n" for line in band_lines] + kept[position:])


# --- documentos do cofre -------------------------------------------------------------------------

VAULT_TITLE = "Documentos do cofre"


@dataclass
class VaultChange:
    """Gravação no cofre preparada (valores só em memória, nunca em resposta ou log)."""
    db_path: Path | str | None
    store: dict[str, str]
    remove: list[str]

    def run(self) -> None:
        from vagas.sensitive import Vault, _mark_profile, default_vault_path

        vault = Vault(default_vault_path(self.db_path), _vault_backend())
        for field, value in self.store.items():
            vault.set(field, value)
            _mark_profile(field, stored=True)
        for field in self.remove:
            if vault.remove(field):
                _mark_profile(field, stored=False)


def _vault_backend():
    from vagas.sensitive import default_backend

    return default_backend()


def load_vault(db_path: Path | str | None) -> dict[str, Any]:
    from vagas.sensitive import ALLOWED_FIELDS, NoVaultBackend, Vault, default_vault_path

    backend = _vault_backend()
    path = default_vault_path(db_path)
    try:
        stored = set(Vault(path, backend).list())
    except (OSError, ValueError):
        stored = set()
    fields = [{"id": field, "title": label, "kind": "secret", "stored": field in stored, "value": "", "hint": "",
               "notes": [], "parent": None, "status": None} for field, label in ALLOWED_FIELDS.items()]
    return {"key": "vault", "title": VAULT_TITLE, "file": str(path), "groups": [{"name": "", "fields": fields}],
            "pending": [], "unavailable": NoVaultBackend.MESSAGE if isinstance(backend, NoVaultBackend) else None,
            "help": "A extensão do Chrome preenche estes documentos nos sites de vagas, com a sua confirmação por "
                    "empresa. Os valores nunca aparecem aqui de novo, nem passam pelo Claude. Senhas, dados "
                    "bancários e cartões não entram no cofre."}


def plan_vault(values: Any, db_path: Path | str | None) -> tuple[VaultChange | None, dict[str, str]]:
    from vagas.sensitive import ALLOWED_FIELDS, NoVaultBackend, valid_cpf

    if not isinstance(values, dict) or set(values) - {"set", "remove"}:
        return None, {"vault": "Envie {set: {documento: valor}, remove: [documentos]}."}
    to_set, to_remove = values.get("set", {}), values.get("remove", [])
    if not isinstance(to_set, dict) or not isinstance(to_remove, list):
        return None, {"vault": "Envie {set: {documento: valor}, remove: [documentos]}."}
    errors: dict[str, str] = {}
    store: dict[str, str] = {}
    for field, value in to_set.items():
        name = f"vault.{field}"
        if field not in ALLOWED_FIELDS:
            errors[name] = "Este dado não pode ir para o cofre."  # nunca ecoa o valor
        elif not isinstance(value, str) or not value.strip():
            errors[name] = "Digite o valor (ou deixe o campo em branco para não mudar)."
        elif "\n" in value or "\r" in value:
            errors[name] = "Use uma linha só."
        elif field == "cpf" and not valid_cpf(value):
            errors[name] = "CPF inválido: os dígitos verificadores não conferem."
        else:
            store[field] = value.strip()
    remove = []
    for field in to_remove:
        if not isinstance(field, str) or field not in ALLOWED_FIELDS:
            errors[f"vault.{field}"] = "Documento desconhecido."
        else:
            remove.append(field)
    if (store or remove) and isinstance(_vault_backend(), NoVaultBackend):
        errors["vault"] = NoVaultBackend.MESSAGE
    if errors:
        return None, errors
    if not store and not remove:
        return None, {}
    return VaultChange(db_path, store, remove), {}
