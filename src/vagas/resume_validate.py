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
        started = False  # marcadores de lista ("-", "•", "1.") não contam como primeira palavra
        for raw in _TOKEN.findall(segment):
            token = _clean(raw)
            if not token:
                continue
            if not any(c.isalnum() for c in token) or re.fullmatch(r"\d+[.)]?", token):
                yield token, False
                continue
            yield token, not started
            started = True


def term_set(texts: Iterable[str]) -> set[str]:
    corpus: set[str] = set()
    for text in texts:
        for token, _ in _tokens(text):
            corpus.add(token.lower())
            corpus.update(part.lower() for part in token.split("-") if part)
    return corpus


def _is_term(token: str, sentence_start: bool) -> bool:
    if not any(c.isalpha() for c in token) or len(token) == 1:
        return False
    if any(c in "+#" for c in token) or (any(c.isdigit() for c in token)):
        return True
    if re.search(r"[A-Za-z]\.[A-Za-z]", token) or token.startswith("."):
        return True
    if sum(c.isupper() for c in token) >= 2:
        return True
    return token[0].isupper() and not sentence_start


def term_candidates(text: str) -> list[str]:
    """Tokens do texto que parecem tecnologia ou nome próprio (inteiros ou por parte hifenizada)."""
    found = []
    for token, sentence_start in _tokens(text):
        parts = [p for p in token.split("-") if p] or [token]
        starts = [sentence_start] + [False] * (len(parts) - 1)
        if any(_is_term(p, s) for p, s in zip(parts, starts)) and token not in found:
            found.append(token)
    return found


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


def match_terms(text: str, corpus: set[str], vocabulary: set[str] = frozenset()) -> tuple[list[str], list[str]]:
    """Termos do texto presentes e ausentes no corpus, sem repetição (ignorando maiúsculas).

    vocabulary (ex.: as skills do currículo) recupera termos em início de frase ou de item de
    lista ("Requirements: Python, SQL"), que de outro modo seriam ignorados como palavra comum.
    """
    unknown = {term.casefold() for term in unknown_terms(text, corpus)}
    terms = set(term_candidates(text))
    matched, missing, seen = [], [], set()
    for token, sentence_start in _tokens(text):
        is_term = token in terms or (sentence_start and token[:1].isupper() and token.lower() in vocabulary)
        if is_term and token.casefold() not in seen:
            seen.add(token.casefold())
            (missing if token.casefold() in unknown else matched).append(token)
    return matched, missing


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


# Anotações sobre as fontes ("PDF lists a certification", "LinkedIn: ...", "segundo o PDF"): são conversa com o
# usuário, não texto de currículo, e sairiam impressas no PDF.
_SOURCE = r"(pdf|linkedin)"
_SOURCE_NOTE = re.compile(
    rf"\b{_SOURCE}\s+(lists?|listed|says|shows|mentions|states|indicates|confirms|lista|diz|mostra|menciona|cita|"
    r"indica|traz|confirma)\b"
    rf"|\b(according\s+to|per|segundo|conforme|de\s+acordo\s+com)\s+(the\s+|o\s+|a\s+)?{_SOURCE}\b"
    rf"|\b{_SOURCE}\s*:"
    rf"|\b(only|not|missing)\s+(in|on|from)\s+(the\s+)?{_SOURCE}\b"
    rf"|\b(consta|aparece|so|apenas)\s+(no|na)\s+{_SOURCE}\b"
    r"|\b(fontes?|sources?)\s*:")
_URL = re.compile(r"\S+://\S+")
# Campos que não saem no PDF (ou são endereços e identificadores).
_NOT_PRINTED = {"id", "links", "link", "headline_variants", "name_original", "credential_id", "description"}


def source_notes(text: str) -> list[str]:
    """Trechos do texto que comentam as fontes do currículo em vez de descrever a pessoa."""
    from vagas.normalize import normalize_text

    plain = normalize_text(_URL.sub(" ", text))
    return [match.group(0) for match in _SOURCE_NOTE.finditer(plain)]


def printed_strings(value, path: str = "") -> Iterator[tuple[str, str]]:
    """(caminho, texto) dos campos impressos; itens de lista são nomeados pelo id, nome ou rótulo."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in _NOT_PRINTED:
                yield from printed_strings(item, f"{path}/{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            name = next((item[k] for k in ("id", "name", "label") if isinstance(item, dict) and item.get(k)), index)
            yield from printed_strings(item, f"{path}/{name}")
    elif isinstance(value, str):
        yield path, value


def source_note_problems(value) -> list[str]:
    return [f"{path}: {text!r} (\"{found[0]}\")" for path, text in printed_strings(value)
            if (found := source_notes(text))]
