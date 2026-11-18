"""Perguntas de formulário que se repetem com o nome de cada empresa ("Você trabalha na empresa X?", "É colaborador
X?", "Have you previously worked at X?", "Foi indicado?"). Reconhecidas por padrão (texto normalizado, PT e EN) e
respondidas pelo currículo geral e por campos genéricos do perfil, nunca por um campo com o nome da empresa. Não
depende de MCP.
"""

import re
from datetime import date
from typing import Any

from vagas.experience import is_current
from vagas.normalize import normalize_company, normalize_text

CURRENT = "atual"  # trabalha hoje na empresa da vaga
PAST = "anterior"  # já trabalhou nela
REFERRAL = "indicacao"  # foi indicado por alguém de lá

COMPANY_NOW = "empresa_atual"  # empresa atual (ou a do último emprego)
TITLE_NOW = "cargo_atual"  # cargo atual (ou o último)
SALARY_NOW = "salario_atual"  # salário atual (ou a última remuneração)
MIN_PAY = "salario_minimo"  # menor salário aceito: o mínimo da faixa da política salarial para a vaga
JOB_KINDS = (COMPANY_NOW, TITLE_NOW, SALARY_NOW)

SECTION = "Respostas padrão"
LAST_PAY_LABEL = "Valor da última remuneração"
LAST_PAY_NOTE = ("Valor mensal e regime (ex.: 10500, PJ). Responde também \"Salário atual\" e \"Current salary\"; "
                 "empresa e cargo atuais saem do currículo geral (sem emprego atual, o último).")
# Nomes das respostas (source). Trabalha e trabalhou saem do currículo geral, empresa por empresa, e não são campos
# do perfil; se estiverem lá (versão anterior), saem na migração. A indicação é o único campo: só o usuário sabe.
CURRENT_LABEL = "Trabalha atualmente na empresa da vaga"
PAST_LABEL = "Já trabalhou na empresa da vaga"
REFERRAL_LABEL = "Foi indicado por alguém da empresa"
LABELS = {CURRENT: CURRENT_LABEL, PAST: PAST_LABEL, REFERRAL: REFERRAL_LABEL}
REFERRAL_NOTE = ("Valores aceitos: Sim ou Não. Vale para todas as empresas (\"Foi indicado?\", \"Alguém que trabalha "
                 "nesta empresa indicou você?\", \"Were you referred?\").")

_JOB = {
    MIN_PAY: tuple(re.compile(p) for p in (
        r"\bminimum (pay|salary|compensation|acceptable salary|expected salary|base salary|monthly salary)\b",
        r"\b(salario|remuneracao|pretensao|valor) (mensal )?minim[ao]\b",
        r"\b(menor|minimo) (salario|valor|remuneracao)\b.*\baceit",
        r"\blowest (salary|pay|compensation)\b",
    )),
    SALARY_NOW: tuple(re.compile(p) for p in (
        r"\b(salario|remuneracao|renda|ganho) (bruto |bruta |mensal )?atual\b",
        r"\bultim[ao] (salario|remuneracao)\b",
        r"\b(current|present|most recent|last|latest|previous) (base |monthly |annual )?(salary|compensation|pay|ctc)\b",
    )),
    TITLE_NOW: tuple(re.compile(p) for p in (
        r"\b(cargo|posicao|funcao|titulo do cargo|ocupacao) atual\b",
        r"\bultim[ao] (cargo|posicao|funcao)\b",
        r"\b(current|present|most recent|last|latest) (job title|title|position|role|job)\b",
    )),
    COMPANY_NOW: tuple(re.compile(p) for p in (
        r"\b(empresa|empregador|companhia|organizacao|instituicao) atual\b",
        r"\bultim[ao] (empresa|empregador)\b",
        r"\b(current|present|most recent|last|latest|previous) (company|employer|organization|organisation)\b",
        r"\b(qual|em qual|em que) (empresa|companhia)\b.*\b(trabalha|atua)\b",
    )),
}
_EMPLOYEE = r"(colaborador|colaboradora|funcionario|funcionaria|empregado|empregada|servidor|servidora)"
_PAST = tuple(re.compile(p) for p in (
    rf"\bja (trabalhou|atuou|trabalhava|foi( um| uma)? {_EMPLOYEE})\b",
    r"\b(trabalhou|atuou) (anteriormente|antes)\b",
    rf"\bex {_EMPLOYEE}\b",
    r"\bhave you (ever |previously |formerly )?(worked|been employed|been an employee)\b",
    r"\b(previously|formerly|ever) (worked|employed)\b",
    r"\b(former|previous) employee\b",
))
_CURRENT_STRONG = tuple(re.compile(p) for p in (
    rf"\b(e|es|sou|voce e)( um| uma| o| a)? {_EMPLOYEE}\b",
    rf"\b{_EMPLOYEE} (atual|ativo|ativa)\b",
    r"\b(current|existing) (employee|team member|staff member|worker)\b",
    r"\b(are|is) you (a |an )?(current )?employee\b",
    r"\b(are|do) you (currently )?(employed by|work for|work at|working at|working for)\b",
))
# "Você trabalha na X?" só vale com empresa à vista: "Você trabalha na área de dados?" não é sobre a empresa.
_CURRENT_WEAK = re.compile(r"\b(trabalha|atua) (atualmente |hoje )?(na|no|em|para|pela|pelo|nesta|nessa|neste|nesse"
                           r"|conosco|aqui)\b")
_COMPANY_WORDS = re.compile(r"\b(empresa|companhia|grupo|organizacao|instituicao|banco|company|group)\b")
_HERE = re.compile(r"\b(nesta|desta|nessa|dessa|esta|essa|nossa|nosso|conosco|aqui|this|our|us)\b")
_REFERRAL = tuple(re.compile(p) for p in (
    r"\bindicad[oa]s?\b", r"\bindicou\b", r"\bindicacao\b", r"\breferr(ed|al|er)s?\b", r"\brefer(red)? by\b",
))
_SOMEONE_ELSE = re.compile(r"\b(parente|parentes|familiar|familiares|conjuge|relative|relatives|family|amigo|amigos"
                           r"|friend|friends|alguem|someone|anyone|conhecido|conhecidos)\b")
_DETAILS = re.compile(r"\b(nome|name|e mail|email|telefone|phone|celular|contato|contact|quem|who|codigo|code)\b")
_GENERIC_TOKENS = {"grupo", "group", "banco", "bank", "empresa", "company", "holding", "brasil", "brazil", "do", "da",
                   "de", "the", "and", "&"}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalize_text(text or "")).split())


def kind(question: str, company: str | None = None) -> str | None:
    """CURRENT, PAST, REFERRAL, COMPANY_NOW, TITLE_NOW, SALARY_NOW, MIN_PAY ou None. company: a empresa da candidatura, que também conta como empresa à vista."""
    norm = _norm(question)
    if any(p.search(norm) for p in _REFERRAL):
        return REFERRAL
    if _SOMEONE_ELSE.search(norm):  # "Algum parente trabalha na empresa?" é sobre outra pessoa
        return None
    for job_kind, patterns in _JOB.items():
        if any(p.search(norm) for p in patterns):
            return job_kind
    if any(p.search(norm) for p in _PAST):
        return PAST
    if any(p.search(norm) for p in _CURRENT_STRONG):
        return CURRENT
    if _CURRENT_WEAK.search(norm) and (_COMPANY_WORDS.search(norm) or _HERE.search(norm)
                                       or (company and mentions(company, question, partial=True))):
        return CURRENT
    return None


def is_generic_label(label: str) -> bool:
    """O campo é um dos genéricos (vale para todas as empresas): pergunta que se repete em toda vaga."""
    return _norm(label) in {_norm(v) for v in (REFERRAL_LABEL, LAST_PAY_LABEL)}


def yes_no(value: str) -> str | None:
    """"Sim", "Não" ou None: a primeira palavra da resposta do perfil ("Não atuei" -> "Não")."""
    word = _norm(value).split(" ")[0] if value and not value.strip().startswith("<") else ""
    return "Sim" if word in {"sim", "yes", "s"} else "Não" if word in {"nao", "no", "n"} else None


def asks_details(question: str) -> bool:
    """A pergunta de indicação pede um dado de quem indicou (nome, e-mail, telefone, código), não sim/não."""
    return _DETAILS.search(_norm(question)) is not None


def points_here(question: str) -> bool:
    """"nesta empresa", "this company": a empresa é a da vaga, sem o nome na pergunta."""
    return _HERE.search(_norm(question)) is not None


def _tokens(name: str) -> set[str]:
    return set(normalize_company(name).split()) if name and name.strip() else set()


def same_company(a: str | None, b: str | None) -> bool:
    """Mesma empresa: nomes normalizados iguais, ou um contém o outro por palavras inteiras ("Itaú" e "Itaú Unibanco
    S.A."); palavras genéricas sozinhas ("Grupo", "Banco") não bastam."""
    first, second = _tokens(a or ""), _tokens(b or "")
    if not first or not second:
        return False
    smaller = first if len(first) <= len(second) else second
    return (first <= second or second <= first) and bool(smaller - _GENERIC_TOKENS)


def mentions(company: str, text: str, partial: bool = False) -> bool:
    """O texto cita a empresa por palavras inteiras (todas; com partial, basta uma que não seja genérica)."""
    tokens, words = _tokens(company), set(_norm(text).split())
    distinctive = tokens - _GENERIC_TOKENS
    if partial:
        return bool(distinctive & words)
    return bool(distinctive) and tokens <= words


def worked_at(periods: list[dict[str, Any]], question: str, company: str | None, current_only: bool,
              today: date) -> list[dict[str, Any]]:
    """As experiências do currículo geral na empresa da vaga (ou na citada na pergunta); só as em andamento com
    current_only."""
    found = []
    for item in periods:
        if current_only and not is_current(item.get("end"), today):
            continue
        name = item.get("company") or ""
        if (company and same_company(name, company)) or mentions(name, question):
            found.append(item)
    return found
