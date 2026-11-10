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
        field = {"id": item.id, "title": item.label, "kind": kind, "value": value, "hint": hint,
                 "notes": [n for n in item.notes if not _norm(n).startswith("valores aceitos")],
                 "parent": item.parent, "status": _locked_status(item) if kind == "locked" else None}
        if kind in ("text", "yesno") and not value:
            pending.append(item.id)
        if not groups or groups[-1]["name"] != (item.section or ""):
            groups.append({"name": item.section or "", "fields": []})
        groups[-1]["fields"].append(field)
    return {"key": "profile", "title": PROFILE_TITLE, "file": str(path), "new": from_example,
            "groups": groups, "pending": pending}


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
        item = by_key.get(md_fields._key(str(field_id)))
        if item is None:
            errors[name] = "Campo desconhecido no perfil."
            continue
        kind = _profile_kind(item, items)
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
            if item.id not in updates and _profile_kind(item, items) in ("text", "yesno") \
                    and not item.value.strip().startswith("<"):
                updates[item.id] = PENDING
    if not updates and not diversity_updates:
        return None, {}
    new_text = md_fields.apply(text, updates)
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
