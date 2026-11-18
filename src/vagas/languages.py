"""Idiomas do perfil: o nível declarado e a certificação, em campos separados. Não depende de MCP.

"Idiomas" guarda o nível que o usuário declara nos formulários ("inglês (avançado)"); "Certificações de idiomas"
guarda o certificado ("inglês (B2, certificado)"), que vale para o currículo e para as perguntas que pedem
certificação ou nível CEFR. O formato antigo juntava os dois na mesma linha ("inglês avançado (B2, certificado)");
`split` separa, para a migração que o usuário confirma.
"""

import re

from vagas.normalize import normalize_text

LANGUAGES_LABEL = "Idiomas"
CERTIFICATIONS_LABEL = "Certificações de idiomas"
LANGUAGES_NOTE = ("Nível que você declara nos formulários (nativo, fluente, avançado, intermediário ou básico). "
                  "A certificação fica em \"Certificações de idiomas\".")
CERTIFICATIONS_NOTE = ("Certificado e nível CEFR (A1 a C2). Vale para o currículo e para as perguntas que pedem "
                       "certificação ou nível CEFR; as demais usam o nível de \"Idiomas\".")

NAMES = {
    "ingles": ("ingles", "english"), "espanhol": ("espanhol", "spanish", "castelhano"),
    "frances": ("frances", "french"), "alemao": ("alemao", "german"), "italiano": ("italiano", "italian"),
    "portugues": ("portugues", "portuguese"), "mandarim": ("mandarim", "chines", "mandarin", "chinese"),
    "japones": ("japones", "japanese"),
}
_LEVEL_STARTS = ("nativ", "fluent", "avancad", "intermedi", "basic", "inician", "elementar")
_CEFR = re.compile(r"\b([abc][12])\b")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+]+", " ", normalize_text(text or "")).split())


def split_top(text: str) -> list[str]:
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
    for raw in split_top(value):
        before, _, inner = raw.partition("(")
        inner = inner.rsplit(")", 1)[0].strip()
        words = before.split()
        cut = next((i for i, w in enumerate(words) if normalize_text(w).startswith(_LEVEL_STARTS)), len(words))
        language, level_words = " ".join(words[:cut]), " ".join(words[cut:])
        level = f"{level_words} ({inner})" if level_words and inner else level_words or inner
        rows.append({"language": language or raw, "level": level, "raw": raw})
    return rows


def key(name: str) -> str | None:
    """A chave do idioma citado no texto ("Nível de inglês" -> "ingles"), ou None."""
    tokens = set(_norm(name).split())
    return next((k for k, names in NAMES.items() if tokens & set(names)), None)


def cefr(text: str) -> str | None:
    """O nível CEFR citado ("A2.3, certificado" -> "a2"), ou None."""
    found = _CEFR.search(_norm(text))
    return found.group(1) if found else None


def _is_word_level(part: str) -> bool:
    return any(w.startswith(_LEVEL_STARTS) for w in _norm(part).split())


def _parts(level: str) -> list[str]:
    """"avançado (B2, certificado)" -> ["avançado", "B2", "certificado"]."""
    before, _, inner = level.partition("(")
    return [p.strip() for p in [*before.split(","), *inner.rsplit(")", 1)[0].split(",")] if p.strip()]


def separate(level: str) -> tuple[str | None, str | None]:
    """(nível declarado, certificação) de um nível no formato antigo; certificação None quando não há CEFR, nível
    declarado None quando só há CEFR."""
    parts = _parts(level)
    declared = [p for p in parts if _is_word_level(p)]
    rest = [p for p in parts if not _is_word_level(p)]
    certification = ", ".join(rest) if any(cefr(p) for p in rest) else None
    if not declared:
        return None, certification
    return " ".join(declared), certification


def levels(languages_value: str | None, certifications_value: str | None) -> dict[str, dict[str, str | None]]:
    """{chave do idioma: {name, declared, certification}}. Uma linha antiga ("avançado (B2, certificado)") vale como
    nível declarado "avançado" e certificação "B2, certificado" até a migração; "Certificações de idiomas" manda na
    certificação."""
    rows: dict[str, dict[str, str | None]] = {}
    for row in parse_languages(languages_value or ""):
        lang = key(row["language"])
        if lang is None:
            continue
        declared, certification = separate(row["level"])
        if declared is None and certification is None:
            declared = row["level"] or None
        rows[lang] = {"name": row["language"], "declared": declared, "certification": certification}
    for row in parse_languages(certifications_value or ""):
        lang = key(row["language"])
        if lang is not None and row["level"]:
            rows.setdefault(lang, {"name": row["language"], "declared": None, "certification": None})
            rows[lang]["certification"] = row["level"]
    return rows


def split(value: str) -> tuple[str, list[str]] | None:
    """Linha antiga de "Idiomas" -> (linha só com os níveis declarados, certificações "idioma (certificação)").
    None quando nenhum idioma junta nível declarado e CEFR na mesma linha."""
    rows, certifications, changed = [], [], False
    for row in parse_languages(value):
        declared, certification = separate(row["level"])
        if declared is not None and certification is not None:
            rows.append(f"{row['language']} ({declared})")
            certifications.append(f"{row['language']} ({certification})")
            changed = True
        else:
            rows.append(row["raw"])
    return (", ".join(rows), certifications) if changed else None


def is_legacy_note(note: str) -> bool:
    """A nota antiga de "Idiomas" que mandava usar o certificado como teto ("mais próxima de B2 / A2...")."""
    norm = _norm(note)
    return "arredondar" in norm or cefr(note) is not None
