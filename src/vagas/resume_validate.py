"""Verificações de "não inventar": números e termos de um texto reescrito precisam existir na fonte.

Funções puras. Termo = token que parece tecnologia ou nome próprio: tem dígitos ou símbolos
(C++, C#, .NET, K3s, GPT-4), duas ou mais maiúsculas (AWS, LLMs) ou começa com maiúscula fora
do início de frase. A comparação ignora maiúsculas/minúsculas.
"""

import re
from collections.abc import Iterable, Iterator

_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*(?:\s?%|[kKmMbB](?![A-Za-z])|\+)?")
_SEGMENT_BREAK = re.compile(r"(?<=[!?|:;])\s+|(?<=[A-Za-z0-9)\]])\.\s+|\n+")
_TOKEN = re.compile(r"[^\s,;:()\[\]{}\"“”‘’/|]+")
_ALLOWED_TERMS = {"i"}


def _canonical_number(raw: str) -> str:
    return raw.replace(" ", "").lower()


def numbers(text: str) -> list[str]:
    """Números do texto, na forma original (ex.: "30%", "2M", "3+")."""
    return [m.group().replace(" ", "") for m in _NUMBER.finditer(text)]


def number_set(texts: Iterable[str]) -> set[str]:
    return {_canonical_number(n) for text in texts for n in numbers(text)}


def _clean(token: str) -> str:
    token = re.sub(r"['’]s$", "", token)
    return token.rstrip(".!?'’").lstrip("'’")


def _tokens(text: str) -> Iterator[tuple[str, bool]]:
    """Tokens com a indicação de início de frase/segmento."""
    for segment in _SEGMENT_BREAK.split(text):
        for i, raw in enumerate(_TOKEN.findall(segment)):
            token = _clean(raw)
            if token:
                yield token, i == 0


def term_set(texts: Iterable[str]) -> set[str]:
    corpus: set[str] = set()
    for text in texts:
        for token, _ in _tokens(text):
            corpus.add(token.lower())
            corpus.update(part.lower() for part in token.split("-") if part)
    return corpus


def _is_term(token: str, sentence_start: bool) -> bool:
    if not any(c.isalpha() for c in token):
        return False
    if any(c in "+#" for c in token) or (any(c.isdigit() for c in token)):
        return True
    if re.search(r"[A-Za-z]\.[A-Za-z]", token) or token.startswith("."):
        return True
    if sum(c.isupper() for c in token) >= 2:
        return True
    return token[0].isupper() and not sentence_start


def unknown_terms(text: str, corpus: set[str]) -> list[str]:
    missing = []
    for token, sentence_start in _tokens(text):
        if token.lower() in corpus or token.lower() in _ALLOWED_TERMS:
            continue
        parts = [p for p in token.split("-") if p] if "-" in token else [token]
        starts = [sentence_start] + [False] * (len(parts) - 1)
        if any(_is_term(p, s) and p.lower() not in corpus for p, s in zip(parts, starts)):
            if token not in missing:
                missing.append(token)
    return missing


def unknown_numbers(text: str, allowed: set[str]) -> list[str]:
    missing = []
    for number in numbers(text):
        if _canonical_number(number) not in allowed and number not in missing:
            missing.append(number)
    return missing


def strings(value) -> Iterator[str]:
    """Todos os textos de uma estrutura JSON (dicts, listas, valores)."""
    if isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, (str, int)) and not isinstance(value, bool):
        yield str(value)
