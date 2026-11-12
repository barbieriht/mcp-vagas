"""Vagas afirmativas: detecta para qual grupo a vaga é direcionada e lê os grupos que o usuário pode disputar.

Não depende de MCP. A detecção é conservadora: exige uma palavra de exclusividade ("exclusiva", "afirmativa",
"destinada a", "only") perto do grupo, ou "vaga/oportunidade/processo para" logo antes dele, na mesma frase, e
ignora negações. Frases de inclusão ("incentivamos candidaturas de mulheres...") não contam. "Vaga afirmativa" sem
grupo reconhecido vira `generic`, para o usuário julgar; declarações da empresa inteira ("todas as nossas vagas são
afirmativas", "affirmative action employer") não.
"""

import re
from dataclasses import dataclass, field

from vagas.normalize import normalize_text
from vagas.repo import VagasError


@dataclass(frozen=True)
class Group:
    label: str  # como aparece nas mensagens
    nouns: str  # regex sobre texto normalizado (minúsculas, sem acento)
    aliases: tuple[str, ...]  # como o usuário pode escrever no arquivo de critérios


GROUPS: dict[str, Group] = {
    "women": Group("mulheres", r"\b(?:mulher(?:es)?|feminin[ao]s?|women|woman|female)\b", ("mulheres", "mulher", "women")),
    "black": Group("pessoas negras",
                   r"\b(?:pessoas? (?:negr[ao]s?|pret[ao]s?)|negr[ao]s?|pret[ao]s?|pard[ao]s?|black|"
                   r"afrodescendentes?)\b",
                   ("pessoas negras", "negras", "negros", "negra", "negro", "pretos e pardos", "black")),
    "lgbt": Group("pessoas LGBTQIA+", r"\b(?:lgbt\w*|pessoas? trans\w*|transgeneros?|travestis?)",
                  ("lgbt", "lgbtqia", "lgbtqia+", "lgbtqiapn+", "pessoas lgbt", "trans")),
    "pcd": Group("PcD", r"\b(?:pcds?|pessoas? com deficiencia)\b",
                 ("pcd", "pcds", "pessoas com deficiencia", "deficiencia")),
    "50plus": Group("pessoas 50+",
                    r"(?:\b[56]\d\s*\+|\b(?:50|55|60)\s*anos\b|maiores de (?:45|50|55|60)|acima de (?:45|50|55|60))",
                    ("50+", "50 mais", "pessoas 50+", "maiores de 50")),
    "indigenous": Group("pessoas indígenas", r"\bindigenas?\b", ("indigenas", "indigena", "pessoas indigenas")),
}
_NONE = {"nenhuma", "nenhum", "nao", "nada"}

_MARKER = (r"(?:exclusiv\w*|afirmativ\w*|destinad\w*|direcionad\w*|dedicad\w*|reservad\w*|somente|apenas|"
           r"so para|only|affirmative)")
# "Vaga para mulheres", "Oportunidade é para pessoas negras": dizem menos que "exclusiva", então o grupo tem de vir logo
# depois ("vaga para trabalhar com dados num time com muitas mulheres" não conta).
_WEAK_MARKER = r"(?:vagas?|oportunidades?|posic(?:ao|oes)|processos?)\s+(?:\w+\s+){0,2}?para\b"
_NEAR, _WEAK_NEAR = 8, 3  # palavras entre a marca e o grupo
# "Women only", "PcD only": a palavra de exclusividade depois do grupo.
_ONLY_AFTER = r"\W+(?:\w+\W+)?only\b"
# Declarações da empresa inteira ("todas as nossas vagas são afirmativas", "affirmative action employer") não dizem
# que esta vaga é de um grupo: não viram `generic`.
_COMPANY_WIDE = re.compile(r"\btodas as (?:nossas )?(?:vagas|oportunidades)\b|\baffirmative action\W+employer|"
                           r"\bequal (?:employment )?opportunit")
_NEGATION = re.compile(r"\b(?:nao|nem|not|sem)\b(?:\W+\w+){0,3}\W*$")
_GENERIC = re.compile(r"\b(?:vagas?|oportunidades?|processos? seletivos?|programas?)\s+afirmativ\w*|"
                      r"\bafirmativ[ao]s?\b|affirmative")
_SENTENCES = re.compile(r"[.!?;\n|•]+")


@dataclass
class Detection:
    groups: list[str] = field(default_factory=list)
    snippets: dict[str, str] = field(default_factory=dict)
    generic: bool = False  # diz "afirmativa" mas nenhum grupo foi reconhecido


def detect(text: str | None) -> Detection:
    """Grupos para os quais a vaga é afirmativa, com o trecho que levou à conclusão."""
    result = Detection()
    saw_generic = False
    for raw in _SENTENCES.split(text or ""):
        sentence = normalize_text(raw)
        if not sentence:
            continue
        saw_generic = saw_generic or bool(_GENERIC.search(sentence)) and not _COMPANY_WIDE.search(sentence)
        for key, group in GROUPS.items():
            if key in result.groups:
                continue
            if _names_group(sentence, group):
                result.groups.append(key)
                result.snippets[key] = " ".join(raw.split())[:120]
    result.generic = saw_generic and not result.groups
    return result


def _names_group(sentence: str, group: Group) -> bool:
    """A frase diz que a vaga é do grupo: palavra de exclusividade perto dele, sem negação antes."""
    for pattern, limit in ((_MARKER, _NEAR), (_WEAK_MARKER, _WEAK_NEAR)):
        for marker in re.finditer(pattern, sentence):
            if _NEGATION.search(sentence[:marker.start()]):
                continue
            window = sentence[marker.end():]
            near = re.search(group.nouns, window)
            if near and len(re.findall(r"\w+", window[:near.start()])) <= limit:
                return True
    after = re.search(group.nouns + _ONLY_AFTER, sentence)
    return bool(after) and not _NEGATION.search(sentence[:after.start()])


def parse_groups(items: list[str], where: str) -> tuple[str, ...]:
    """Itens da linha de critérios ("Mulheres, pessoas negras.") -> chaves dos grupos."""
    found: list[str] = []
    for item in items:
        norm = normalize_text(item).rstrip(".; ")
        if norm in _NONE:
            continue
        key = next((k for k, g in GROUPS.items() if norm in g.aliases), None)
        if key is None:
            accepted = ", ".join(g.label.removeprefix("pessoas ") if k != "black" else g.label
                                 for k, g in GROUPS.items())
            raise VagasError(f"Grupo desconhecido em {where}: {item.strip()}. Valores aceitos: {accepted}, "
                             "ou nenhuma (maiúsculas, acentos e ponto final são ignorados).")
        found.append(key)
    return tuple(dict.fromkeys(found))


def labels(keys: list[str] | tuple[str, ...]) -> str:
    return ", ".join(GROUPS[k].label for k in keys)
