"""Nome do arquivo do currículo personalizado: <Empresa>_<sigla do cargo>_<ID da candidatura>.pdf.

Sem o nome da pessoa, que seria sempre o mesmo. Curto o bastante para os sites que limitam o nome do arquivo
(o Bradesco recusa mais de 50 caracteres): a empresa é encurtada antes do cargo, e o ID da candidatura torna o
nome único mesmo com duas vagas iguais na mesma empresa. Não depende de MCP.
"""

import re
import unicodedata

MAX_STEM = 36  # sem ".pdf"; com um "_2" de arquivo repetido e a extensão, até 42 caracteres
_COMPANY_MAX = 20
_COMPANY_SUFFIXES = {"sa", "s", "a", "ltda", "me", "eireli", "inc", "llc", "corp", "corporation", "ltd", "limited",
                     "gmbh", "plc", "co"}
_STOP = {"de", "da", "do", "das", "dos", "e", "em", "of", "and", "the", "a", "o", "para", "com", "na", "no", "in",
         "for", "to"}

# Famílias de cargo com sigla fixa (texto normalizado: minúsculas, sem acento).
_FAMILIES = (
    ("MLOps", r"\bmlops\b"),
    ("MLE", r"\b(machine learning|ml)\b.*\b(engineer|engenheir\w*)\b|\b(engineer|engenheir\w*)\b.*\b(machine learning|ml)\b"),
    ("AIE", r"\b(ai|ia|inteligencia artificial|genai|llm)\b.*\b(engineer|engenheir\w*)\b"
            r"|\b(engineer|engenheir\w*)\b.*\b(ai|ia|inteligencia artificial|genai|llm)\b"),
    ("DS", r"\bdata scien\w*|\bcientista de dados\b|\bciencias? de dados\b"),
    ("DE", r"\bdata engineer\w*|\bengenheir\w* de dados\b"),
    ("DA", r"\bdata analy\w*|\banalista de dados\b"),
)
_SENIORITY = (("Est", ("estagio", "estagiario", "estagiaria", "intern", "internship")),
              ("Jr", ("junior", "jr")), ("Pl", ("pleno", "pl", "mid")), ("Sr", ("senior", "sr")),
              ("Esp", ("especialista", "specialist")), ("Staff", ("staff",)), ("Princ", ("principal",)),
              ("Lead", ("lead", "lider")))
_LEVEL = re.compile(r"\b(I{1,3}|IV|V)\b")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


def _slug(text: str) -> str:
    return "_".join(re.findall(r"[A-Za-z0-9]+", _ascii(text)))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _ascii(text).lower())


def _main_part(role: str) -> str:
    """O cargo sem os parênteses e sem o que vem depois de "|" ou " - " (modalidade, local, idioma)."""
    text = re.sub(r"\([^)]*\)", " ", role or "")
    parts = [p for p in re.split(r"\s+[|–—-]\s+|\|", text) if re.search(r"[A-Za-z]", p)]
    return parts[0].strip() if parts else text.strip()


def role_code(role: str) -> str:
    """"Data Scientist III" -> "DS_III"; "Analista de Modelagem II" -> "AM_II"; "Senior ML Engineer" -> "MLE_Sr"."""
    main = _main_part(role)
    norm = " ".join(_words(main))
    family = next((code for code, pattern in _FAMILIES if re.search(pattern, norm)), None)
    seniority_words = {w for _, words in _SENIORITY for w in words}
    if family is None:
        initials = [w[0].upper() for w in _words(main) if w not in _STOP and w not in seniority_words
                    and not re.fullmatch(r"i{1,3}|iv|v|\d+", w)]
        family = "".join(initials[:4]) or "CV"
    whole = set(_words(role))
    seniority = next((code for code, words in _SENIORITY if whole & set(words)), None)
    level = next(iter(_LEVEL.findall(_ascii(main))), None)
    return "_".join(p for p in (family, seniority, level) if p)


def _company(company: str, room: int) -> str:
    words = _slug(company).split("_")
    while len(words) > 1 and words[-1].lower() in _COMPANY_SUFFIXES:
        words.pop()
    kept: list[str] = []
    for word in words:
        if len("_".join([*kept, word])) > room:
            break
        kept.append(word)
    return "_".join(kept) or words[0][:room]


def application_stem(company: str, role: str, application_id: int) -> str:
    """<Empresa>_<sigla do cargo>_<ID>, com no máximo MAX_STEM caracteres (a empresa encolhe primeiro)."""
    tail = f"{role_code(role)}_{application_id}"
    room = max(4, min(_COMPANY_MAX, MAX_STEM - len(tail) - 1))
    return f"{_company(company, room)}_{tail}"[:MAX_STEM].rstrip("_")


def label_stem(label: str | None) -> str:
    """Currículo sem candidatura ligada (ex.: o geral): Curriculo_<rótulo>."""
    slug = _slug(label or "")
    if not slug:
        return "Curriculo"
    stem = f"Curriculo_{slug}"
    return stem if len(stem) <= MAX_STEM else stem[:MAX_STEM + 1].rsplit("_", 1)[0]
