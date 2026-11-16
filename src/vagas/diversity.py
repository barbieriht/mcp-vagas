"""Perguntas de diversidade e inclusão dos formulários: um campo por pergunta no perfil (seção "Diversidade e
inclusão"), com as opções que os formulários costumam oferecer. Não depende de MCP.

Também lê o formato antigo (um campo "Diversidade" com as respostas em subitens, rotulados ou soltos, como
"Sexo: Masculino" ou "Homem cisgênero") para propor a migração. A proposta nunca escolhe uma opção por
adivinhação: resposta que cita duas opções de uma lista fechada (ex.: "Pardo/Indígena") fica sem valor.
Nada aqui infere a resposta por nome, foto ou contexto.
"""

import re
from dataclasses import dataclass

from vagas.normalize import normalize_text

SECTION = "Diversidade e inclusão"
NOT_SAY = "Prefiro não responder"
DISABILITY = "Possui deficiência"


@dataclass(frozen=True)
class Question:
    label: str
    options: tuple[str, ...]
    keys: tuple[tuple[str, tuple[str, ...]], ...]  # (opção, começos de palavra que a identificam)
    words: tuple[str, ...]  # palavras que identificam a pergunta numa linha solta do formato antigo
    closed: bool  # lista fechada: resposta fora dela não vale (aberta: o texto do usuário vale)
    first_match: bool = False  # a primeira opção reconhecida vence (senão, duas opções = sem resposta)
    aliases: tuple[str, ...] = ()


QUESTIONS: tuple[Question, ...] = (
    Question(DISABILITY, ("Sim", "Não"),
             (("Não", ("nao", "nenhum")), ("Sim", ("sim", "possuo", "tenho", "pcd"))),
             ("deficien", "pcd"), closed=True, first_match=True, aliases=("pessoa com deficiencia", "pcd")),
    Question("Cor/raça (IBGE)", ("Branca", "Preta", "Parda", "Amarela", "Indígena"),
             (("Branca", ("branc",)), ("Preta", ("pret",)), ("Parda", ("pard",)), ("Amarela", ("amarel",)),
              ("Indígena", ("indigen",))),
             ("raca", "etnia", "cor", "branc", "pret", "negr", "pard", "amarel", "indigen", "latin"), closed=True,
             aliases=("raca/etnia", "raca", "cor/raca", "raca/cor", "cor", "etnia")),
    Question("Sexo", ("Masculino", "Feminino", "Intersexo"), (), ("sexo", "masc", "femin", "intersex"), closed=False),
    Question("Identidade de gênero", ("Homem cisgênero", "Mulher cisgênera", "Homem transgênero",
                                      "Mulher transgênera", "Não binário", "Travesti"), (),
             ("identidade de genero", "genero", "cis", "trans", "binari", "travesti"), closed=False),
    Question("Orientação sexual", ("Heterossexual", "Gay", "Lésbica", "Bissexual", "Pansexual", "Assexual"), (),
             ("orientacao sexual", "orientacao", "hetero", "homo", "gay", "lesbic", "bissex", "pansex", "assex"),
             closed=False),
)


def _norm(text: str) -> str:
    return " ".join(normalize_text(text or "").split())


def question(label: str) -> Question | None:
    """Pergunta pelo rótulo do perfil, inclusive os antigos ("Raça/etnia")."""
    key = _norm(label)
    return next((q for q in QUESTIONS if key == _norm(q.label) or key in q.aliases), None)


def is_old_block(label: str) -> bool:
    """O campo "Diversidade" do formato antigo (respostas em subitens)."""
    return _norm(label).startswith("diversidade") and question(label) is None


def canonical(q: Question, text: str | None) -> str | None:
    """A opção que a resposta escolhe, "Prefiro não responder", ou, em pergunta aberta, o próprio texto.
    None quando não há resposta ou ela não escolhe uma opção só de uma lista fechada."""
    answer = (text or "").strip().rstrip(".")
    if not answer or answer.startswith("<"):
        return None
    norm = _norm(answer)
    if norm.startswith("prefiro nao"):
        return NOT_SAY
    if exact := next((o for o in q.options if _norm(o) == norm), None):
        return exact
    tokens = re.findall(r"[a-z]+", norm)
    found = [option for option, starts in q.keys if any(t.startswith(s) for t in tokens for s in starts)]
    if q.first_match and found:
        return found[0]
    if len(found) == 1:
        return found[0]
    return None if q.closed else answer


def disability(value: str | None) -> str:
    """Resposta de "Possui deficiência": sim, nao, nao_informado (prefere não responder) ou pendente."""
    answer = canonical(QUESTIONS[0], value)
    return {"Sim": "sim", "Não": "nao", NOT_SAY: "nao_informado"}.get(answer or "", "pendente")


def _strip_question(text: str, words: tuple[str, ...]) -> str:
    """"Sexo Masculino" -> "Masculino"; "Raça: Parda" -> "Parda"."""
    norm = _norm(text)
    for word in words[:3]:
        if norm.startswith(word + " ") or norm.startswith(word + ":"):
            return text.strip()[len(word) + 1:].strip(" :")
    return text.strip()


def old_answers(children: list[str]) -> dict[str, str]:
    """Respostas do formato antigo por pergunta (rótulo novo -> texto como o usuário escreveu), lidas dos
    subitens rotulados ("Sexo: Masculino") ou soltos ("Homem cisgênero"). Linha que não identifica a
    pergunta fica de fora."""
    answers: dict[str, str] = {}
    loose = []
    for child in children:
        label, sep, value = child.partition(":")
        q = question(label) if sep else None
        if q is not None:
            if value.strip() and not value.strip().startswith("<"):
                answers[q.label] = value.strip()
        else:
            loose.append(child.strip())
    for line in loose:
        placed = next((q for q in QUESTIONS if q.label not in answers
                       and any(_norm(o) == _norm(_strip_question(line, q.words)) for o in (*q.options, NOT_SAY))), None)
        if placed is None:
            placed = next((q for q in QUESTIONS if q.label not in answers and any(w in _norm(line) for w in q.words)),
                          None)
        if placed is not None:
            answers[placed.label] = _strip_question(line, placed.words)
    return answers


def proposal(children: list[str], present: set[str]) -> list[dict[str, str | None]]:
    """Campos novos para as perguntas que o perfil ainda não tem: {label, value (None = a preencher), from}."""
    answers = old_answers(children)
    have = {_norm(label) for label in present}
    rows = []
    for q in QUESTIONS:
        if _norm(q.label) in have:
            continue
        original = answers.get(q.label)
        rows.append({"label": q.label, "value": canonical(q, original), "from": original})
    return rows
