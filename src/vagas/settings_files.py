"""Seções do painel que editam arquivos pessoais em Markdown: perfil para formulários e critérios de triagem.

Cada seção sabe ler o arquivo para o formulário (`load`) e preparar a gravação (`plan`), sem gravar: o
settings_form valida todas as seções antes de gravar qualquer uma. A leitura e a troca de valores ficam
em md_fields, que preserva o resto do arquivo; a validação dos critérios usa o mesmo parse_criteria da
triagem. Arquivo inexistente nasce do .example.md. Não depende de HTTP nem de MCP.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vagas import affirmative, md_fields
from vagas.models import ROLE_KEYS, ROLE_NAMES, SENIORITIES, SENIORITY_LABELS
from vagas.normalize import normalize_text
from vagas.profile_fields import MANUAL, TALENT_POOL, default_skill_dir, is_sensitive
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


# Diversidade: uma pergunta por campo, com as opções mais comuns nos formulários (IBGE para raça/cor),
# "Prefiro não responder" e texto livre ("Outra") para qualquer resposta fora da lista.
NOT_SAY = "Prefiro não responder"
DIVERSITY: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # (rótulo, opções, prefixos e palavras que identificam a pergunta numa linha solta)
    ("Sexo", ("Masculino", "Feminino", "Intersexo"), ("sexo", "masc", "femin", "intersex")),
    ("Identidade de gênero", ("Homem cisgênero", "Mulher cisgênera", "Homem transgênero", "Mulher transgênera",
                              "Não binário", "Travesti"),
     ("identidade de genero", "genero", "cis", "trans", "binari", "travesti")),
    ("Orientação sexual", ("Heterossexual", "Gay", "Lésbica", "Bissexual", "Pansexual", "Assexual"),
     ("orientacao sexual", "orientacao", "hetero", "homo", "gay", "lesbic", "bissex", "pansex", "assex")),
    ("Raça/etnia", ("Branca", "Preta", "Parda", "Amarela", "Indígena"),
     ("raca/etnia", "raca", "etnia", "cor", "branc", "pret", "negr", "pard", "amarel", "indigen", "latin")),
)


def _is_diversity(item: md_fields.Item) -> bool:
    return item.parent is None and _norm(item.label).startswith("diversidade")


def _strip_question(text: str, words: tuple[str, ...]) -> str:
    """"Sexo Masculino" -> "Masculino"; "Raça: Parda" -> "Parda"."""
    norm = _norm(text)
    for word in words[:3]:
        if norm.startswith(word + " ") or norm.startswith(word + ":"):
            return text.strip()[len(word) + 1:].strip(" :")
    return text.strip()


def _diversity_answers(parent: md_fields.Item, items: list[md_fields.Item]) -> tuple[dict[str, str], list[str]]:
    """Respostas atuais por pergunta, lidas dos subcampos ("Sexo: Masculino") ou de linhas soltas
    ("Sexo Masculino", "Homem cisgênero"). Linhas que não identificam a pergunta voltam em `extra`."""
    answers = {label: "" for label, _, _ in DIVERSITY}
    for child in items:
        if child.parent == parent.label and child.section == parent.section:
            label = next((lb for lb, _, words in DIVERSITY if _norm(child.label).startswith(words[0].split("/")[0])
                          or _norm(child.label) in words[:3]), None)
            value = child.value.strip()
            if label and not value.startswith("<"):
                answers[label] = value
    extra = []
    for note in parent.notes:
        placed = False
        for label, options, words in DIVERSITY:
            answer = _strip_question(note, words)
            exact = next((o for o in (*options, NOT_SAY) if _norm(o) == _norm(answer)), None)
            if exact and not answers[label]:
                answers[label], placed = exact, True
                break
        if not placed:
            for label, _, words in DIVERSITY:
                if not answers[label] and any(word in _norm(note) for word in words):
                    answers[label], placed = _strip_question(note, words), True
                    break
        if not placed:
            extra.append(note)
    return answers, extra


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
    if _norm(item.label) == "idiomas" and item.parent is None:
        return "languages"
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
    diversity_parents = {(i.section, i.label) for i in items if _is_diversity(i)}
    for item in items:
        if item.label.startswith("<"):
            continue  # linha-modelo do exemplo ("<Rótulo do campo ...>"), não é campo
        if (item.section, item.parent) in diversity_parents:
            continue  # subcampos da diversidade: viram os campos de escolha abaixo
        if _is_diversity(item):
            answers, _ = _diversity_answers(item, items)
            if not groups or groups[-1]["name"] != (item.section or ""):
                groups.append({"name": item.section or "", "fields": []})
            groups[-1]["fields"].append({"id": item.id, "title": "Diversidade", "kind": "group", "value": "", "hint": "",
                                         "notes": ["Respostas usadas nos formulários. \"Prefiro não responder\" "
                                                   "vale em todas."], "parent": None, "status": None})
            for label, options, _ in DIVERSITY:
                field_id = f"{item.id}/{label}"
                groups[-1]["fields"].append({"id": field_id, "title": label, "kind": "choice_other",
                                             "choices": [*options, NOT_SAY], "value": answers[label], "hint": "",
                                             "notes": [], "parent": item.label, "status": None})
                if not answers[label]:
                    pending.append(field_id)
            continue
        kind = _profile_kind(item, items)
        placeholder = item.value.strip().startswith("<")
        value = "" if placeholder else item.value.strip()
        hint = _hint(item.value) if placeholder else ""
        if from_example and kind in ("text", "yesno") and not placeholder:
            hint, value = value, ""  # o exemplo é dica, nunca valor de outra pessoa
        if kind == "yesno":
            value = _yes_no(value)
        if kind == "languages":
            rows = parse_languages(item.value) if not placeholder else []
            value, hint = ([], "") if from_example else (rows, "")
            hint_rows = rows if from_example else []
        field = {"id": item.id, "title": item.label, "kind": kind, "value": value, "hint": hint,
                 **({"levels": list(LANGUAGE_LEVELS), "hint_rows": hint_rows} if kind == "languages" else {}),
                 "notes": [n for n in item.notes if not _norm(n).startswith("valores aceitos")],
                 "parent": item.parent, "status": _locked_status(item) if kind == "locked" else None}
        if kind in ("text", "yesno", "languages") and not value:
            pending.append(item.id)
        if not groups or groups[-1]["name"] != (item.section or ""):
            groups.append({"name": item.section or "", "fields": []})
        groups[-1]["fields"].append(field)
    if not from_example:
        for item, kind in _missing_from_example(items, example):
            field = {"id": item.id, "title": item.label, "kind": kind, "value": "", "missing": True,
                     "hint": _hint(item.value) if item.value.strip().startswith("<") else item.value.strip(),
                     "notes": [n for n in item.notes if not _norm(n).startswith("valores aceitos")],
                     "parent": None, "status": None}
            group = next((g for g in groups if g["name"] == (item.section or "")), None)
            if group is None:
                group = {"name": item.section or "", "fields": []}
                groups.append(group)
            group["fields"].append(field)
    return {"key": "profile", "title": PROFILE_TITLE, "file": str(path), "new": from_example,
            "groups": groups, "pending": pending}


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
        if item.parent or item.label.startswith("<") or _is_diversity(item):
            continue
        if md_fields._key(item.id) in have or _norm(item.label) in have_labels:
            continue
        kind = _profile_kind(item, example_items)
        if kind in ("text", "yesno"):
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
    diversity_keys = {md_fields._key(f"{i.id}/{label}"): (i, label) for i in items if _is_diversity(i)
                      for label, _, _ in DIVERSITY}
    updates: dict[str, str] = {}
    diversity_updates: dict[str, dict[str, str]] = {}
    errors: dict[str, str] = {}
    for field_id, raw in values.items():
        name = f"profile.{field_id}"
        if (target := diversity_keys.get(md_fields._key(str(field_id)))) is not None:
            if not isinstance(raw, str) or "\n" in raw or "\r" in raw or raw.strip().startswith("<"):
                errors[name] = "Escolha uma opção ou escreva a resposta numa linha só."
            else:
                diversity_updates.setdefault(target[0].id, {})[target[1]] = raw.strip()
            continue
        if (new := missing.get(md_fields._key(str(field_id)))) is not None:
            new_item, new_kind = new
            if not isinstance(raw, str) or "\n" in raw or "\r" in raw or raw.strip().startswith("<"):
                errors[name] = "Informe o valor numa linha só (sem começar com '<')."
            elif new_kind == "yesno" and raw.strip() and not _yes_no(raw):
                errors[name] = "Responda sim ou não."
            elif raw.strip():  # vazio: o campo continua fora do arquivo
                value = _yes_no(raw) if new_kind == "yesno" else raw.strip()
                inserts.append((new_item.section, f"- {new_item.label}: {value}"))
            continue
        item = by_key.get(md_fields._key(str(field_id)))
        if item is None:
            errors[name] = "Campo desconhecido no perfil."
            continue
        kind = _profile_kind(item, items)
        if kind == "languages":
            line, row_errors = _check_languages(raw, name)
            errors.update(row_errors)
            if not row_errors:
                updates[item.id] = line or PENDING
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
            if item.id not in updates and _profile_kind(item, items) in ("text", "yesno", "languages") \
                    and not item.value.strip().startswith("<"):
                updates[item.id] = PENDING
    if not updates and not diversity_updates and not inserts:
        return None, {}
    new_text = md_fields.apply(text, updates)
    for section, line in inserts:
        new_text = md_fields.insert_item(new_text, section, line)
    for parent_id, changed in diversity_updates.items():
        parent = next(i for i in md_fields.parse(new_text) if i.id == parent_id)
        answers, extra = _diversity_answers(parent, md_fields.parse(new_text))
        answers.update(changed)
        lines = [f"  - {label}: {answers[label] or '<...>'}" for label, _, _ in DIVERSITY]
        new_text = md_fields.replace_children(new_text, parent_id, lines + [f"  - {note}" for note in extra])
    return Pending(path, new_text), {}


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
HIDDEN_CRITERIA = {"pcd_terms"}

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
    "affirmative_ok": "Grupos cujas vagas afirmativas você quer disputar. Nenhum marcado: nenhuma.",
    "accepted_locations": "Cidades aceitas para vagas híbridas e presenciais, separadas por vírgula. Remotas são "
                          "sempre aceitas.",
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


def load_criteria(db_path: Path | str | None) -> dict[str, Any]:
    try:
        path, example = _criteria_paths(db_path)
        text, from_example = _source(path, example)
    except VagasError as exc:
        return _error_section("criteria", CRITERIA_TITLE, str(exc))
    fields = []
    for item in md_fields.parse(text):
        name = _criteria_field(item.label)
        if name is None or item.parent or name in HIDDEN_CRITERIA:
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
    for field_id, raw in values.items():
        name = f"criteria.{field_id}"
        item = by_key.get(md_fields._key(str(field_id)))
        field = _criteria_field(item.label) if item else None
        if field is None:
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
    if not updates:
        return None, {}
    new_text = md_fields.apply(text, updates)
    try:
        parse_criteria(new_text, source=path.name)
    except VagasError as exc:
        return None, {"criteria": str(exc)}
    return Pending(path, new_text), {}


# --- política salarial -------------------------------------------------------------------------

POLICY_TITLE = "Política salarial"
_MODE_LABELS = {"minimo": "Mínimo", "faixa": "Faixa"}
_BAND_LINE = re.compile(r"^(?P<label>.+?)\s*\((?P<tags>[^)]*)\)$")


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
        rows.append((item, {"name": key["label"].strip(), "currency": currency, "clt": "CLT" in tags,
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
        row["applies"] = _applies(row["name"])
        row["hint_min"], row["hint_max"] = row["min"], row["max"]
        if from_example:
            row["min"] = row["max"] = ""  # salário é pessoal: o exemplo só sugere as faixas
        rows.append(row)
    fields.append({"id": "Faixas", "title": "Faixas", "kind": "bands", "value": rows, "currencies": list(CURRENCIES),
                   "hint": "", "notes": [], "parent": None, "status": None,
                   "help": "Valores mensais. A faixa vale para as modalidades citadas no nome (remoto, híbrido, "
                           "presencial; nenhuma = todas) e para as cidades depois de \"em\" (nenhuma = qualquer local). "
                           "Moedas nunca são convertidas entre si."})
    pending = ["Faixas"] if from_example or not rows else []
    return {"key": "policy", "title": POLICY_TITLE, "file": str(path), "new": from_example,
            "groups": [{"name": "", "fields": fields}], "pending": pending}


def _band_line(row: dict[str, Any]) -> str:
    tags = row["currency"] + (", CLT" if row["clt"] else "")
    if row["alias"]:
        return f"- {row['name']} ({tags}): usar a faixa do {row['alias']}"
    value = f"mínimo {_number_text(row['min'])}"
    if row["max"].strip():
        value += f", máximo {_number_text(row['max'])}"
    return f"- {row['name']} ({tags}): {value}"


def _check_bands(rows: Any, mode: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    from vagas.models import CURRENCIES
    from vagas.salary_policy import parse_number

    if not isinstance(rows, list):
        return [], {"policy.Faixas": "Envie as faixas como uma lista."}
    if not rows:
        return [], {"policy.Faixas": "Cadastre pelo menos uma faixa."}
    clean, errors = [], {}
    names = [normalize_text(str(r.get("name", "")).strip()) if isinstance(r, dict) else "" for r in rows]
    for index, row in enumerate(rows):
        where = f"policy.Faixas.{index}"
        if not isinstance(row, dict):
            errors[where] = "Faixa inválida."
            continue
        text = {k: str(row.get(k, "") or "").strip() for k in ("name", "currency", "min", "max", "alias")}
        if any("\n" in v or "\r" in v for v in text.values()):
            errors[where] = "Use uma linha só em cada campo."
            continue
        if not text["name"]:
            errors[f"{where}.name"] = "Dê um nome à faixa (ex.: Remoto nacional)."
        elif re.search(r"[():]", text["name"]):
            errors[f"{where}.name"] = "O nome não pode ter parênteses nem dois-pontos."
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
        clean.append({**text, "currency": text["currency"].upper(), "clt": bool(row.get("clt"))})
    return clean, errors


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
    current_rows = [row for _, row in _band_items(text)]
    if from_example and "Faixas" not in values:
        return None, {**errors, "policy.Faixas": "Preencha os valores das faixas."}
    rows, band_errors = _check_bands(values.get("Faixas", current_rows), mode)
    errors.update(band_errors)
    if errors:
        return None, errors
    new_text = md_fields.apply(text, updates)
    if "Faixas" in values or from_example:
        new_text = _replace_bands(new_text, [_band_line(row) for row in rows])
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
