"""Cargos: os que o usuário mira (texto livre, sugeridos pelo currículo geral) e um dicionário de famílias conhecidas.
Não depende de MCP.

Os critérios de triagem dizem os cargos alvo em texto livre ("Desenvolvedor Backend", "Product Manager (PM, Gerente
de Produto)": entre parênteses, sinônimos). Cada um vira um `Role` com uma chave (slug) usada na triagem e na
pesquisa salarial. As famílias de dados (PRESETS) não são padrão de ninguém: são só sinônimos PT/EN conhecidos,
para "data_scientist" ou "Cientista de Dados" nos critérios valerem como sempre valeram.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from vagas.languages import split_top
from vagas.models import ROLE_NAMES
from vagas.normalize import normalize_text

KEY = re.compile(r"^[a-z0-9_]+$")
_STOP = {"de", "da", "do", "das", "dos", "em", "e", "a", "o", "para", "com", "of", "the", "and", "for", "in", "to",
         "at"}
SENIORITY_WORDS = {"estagio", "estagiario", "estagiaria", "intern", "internship", "trainee", "junior", "jr",
                   "pleno", "pl", "mid", "senior", "sr", "especialista", "specialist", "lead", "lider", "staff",
                   "principal", "i", "ii", "iii", "iv", "v"}
_PRESET_PATTERNS = {
    "ml_engineer": r"(machine learning|\bml\b).*(engineer|engenh|\beng\b)|(engineer|engenh|\beng\b).*(machine learning"
                   r"|\bml\b)|\bmle\b|visao computacional|computer vision",
    "ai_engineer": r"\b(ai|llm|genai)\b.*engineer|(engenh|desenvolvedor|developer)\w*.*\b(ia|ai|inteligencia artificial)\b",
    "data_scientist": r"data scien|cientista (de )?dados|ciencia de dados",
    "data_engineer": r"data engineer|engenheir\w*(\(a\))? de dados",
    "data_analyst": r"data analyst|analista de (dados|bi)\b|\bbi analyst",
}


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9()]+", " ", normalize_text(text or "")).split())


def _stem(word: str) -> str:
    """Sem plural nem gênero: "engenheiras" e "engenheiro" -> "engenheir"."""
    if len(word) > 3 and word.endswith("s"):
        word = word[:-1]
    if len(word) > 4 and word[-1] in "ao":
        word = word[:-1]
    return word


def _stems(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", normalize_text(text or ""))
    return {_stem(w) for w in words if w not in _STOP and w not in SENIORITY_WORDS}


def slug(text: str) -> str:
    return "_".join(w for w in re.findall(r"[a-z0-9]+", normalize_text(text or "")) if w not in SENIORITY_WORDS)


@dataclass(frozen=True)
class Role:
    key: str
    names: tuple[str, ...]  # o primeiro é o nome principal; os demais, sinônimos (e o nome em inglês, nos presets)
    pattern: str | None = None  # regex dos presets, sobre o título sem acento
    preset: bool = False
    _stems: tuple[frozenset[str], ...] = field(default=(), compare=False, repr=False)

    @property
    def name(self) -> str:
        return self.names[0]

    def matches(self, title: str) -> bool:
        if self.pattern and re.search(self.pattern, _plain(title)):
            return True
        words = _stems(title)
        return any(stems and stems <= words for stems in self._stems)


def _custom(key: str, names: tuple[str, ...]) -> Role:
    return Role(key, names, _stems=tuple(frozenset(_stems(n)) for n in names))


PRESETS: tuple[Role, ...] = tuple(
    Role(key, names, _PRESET_PATTERNS[key], True, tuple(frozenset(_stems(n)) for n in names))
    for key, names in sorted(ROLE_NAMES.items(), key=lambda kv: list(_PRESET_PATTERNS).index(kv[0])))
_BY_KEY = {r.key: r for r in PRESETS}


def parse(item: str) -> Role | None:
    """"data_scientist", "Cientista de Dados" -> o preset; "Product Manager (PM, Gerente de Produto)" -> cargo livre
    com sinônimos. None para texto vazio."""
    text = " ".join((item or "").split()).strip(" .;")
    if not text:
        return None
    main, _, rest = text.partition("(")
    main = main.strip()
    synonyms = tuple(s.strip() for s in rest.rsplit(")", 1)[0].split(",") if s.strip()) if rest else ()
    key = re.sub(r"[\s-]+", "_", normalize_text(text))
    if key in _BY_KEY:
        return _BY_KEY[key]
    norm = normalize_text(main)
    preset = next((r for r in PRESETS if norm in r.names), None)
    if preset is not None and not synonyms:
        return preset
    key = slug(main) or slug(text)
    if not key:
        return None
    return _custom(key, (main, *synonyms))


def parse_list(value: str) -> tuple[Role, ...]:
    """Lista dos critérios, separada por vírgula fora dos parênteses (sinônimos)."""
    found = {}
    for item in split_top(value or ""):
        role = parse(item)
        if role is not None:
            found.setdefault(role.key, role)
    return tuple(found.values())


def catalog(roles: tuple[Role, ...] = ()) -> tuple[Role, ...]:
    """Os cargos dos critérios primeiro (são os do usuário), depois os presets que eles não repetem."""
    keys = {r.key for r in roles}
    return (*roles, *(r for r in PRESETS if r.key not in keys))


def classify(title: str, roles: tuple[Role, ...] = ()) -> Role | None:
    return next((r for r in catalog(roles) if r.matches(title)), None)


def names(key: str, roles: tuple[Role, ...] = ()) -> tuple[str, ...]:
    """Nomes do cargo para buscas e pesquisa salarial; chave desconhecida: a própria chave legível."""
    role = next((r for r in catalog(roles) if r.key == key), None)
    return role.names if role else (key.replace("_", " "),)


def label(role: Role) -> str:
    """Como o cargo se escreve nos critérios: o nome com os sinônimos entre parênteses (presets: o nome)."""
    if role.preset:
        return role.name[:1].upper() + role.name[1:]
    return f"{role.name} ({', '.join(role.names[1:])})" if len(role.names) > 1 else role.name


# --- sugestões a partir do currículo geral --------------------------------------------------------

def _without_seniority(title: str) -> str:
    words = [w for w in re.split(r"(\s+)", title.strip()) if w.strip()]
    kept = [w for w in words if normalize_text(w).strip("()[],.-") not in SENIORITY_WORDS]
    return " ".join(kept).strip(" -–,|")


def suggest_from_resume(master: dict[str, Any] | None) -> list[dict[str, str]]:
    """Cargos tirados do currículo geral, os mais recentes primeiro: títulos das experiências e os aliases, e as
    partes da headline (separadas por "|"). Sem palavras de senioridade ("Data Scientist Intern" -> "Data
    Scientist"), sem repetir o mesmo cargo."""
    if not master:
        return []
    found: dict[str, dict[str, str]] = {}

    def add(text: str | None, origin: str) -> None:
        name = _without_seniority(text or "")
        key = " ".join(sorted(_stems(name)))
        if name and key and key not in found:
            found[key] = {"name": name, "from": origin}

    for item in master.get("experience") or []:
        add(item.get("title"), f"experiência: {item.get('title')} — {item.get('company')}")
        for alias in item.get("title_aliases") or []:
            add(alias, f"outro título de {item.get('title')} — {item.get('company')}")
    basics = master.get("basics") or {}
    for headline in [basics.get("headline"), *(master.get("headline_variants") or basics.get("headline_variants")
                                               or [])]:
        for part in re.split(r"[|/•·]", headline or ""):
            add(part, "headline")
    return list(found.values())
