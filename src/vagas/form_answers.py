"""Resposta de uma pergunta de formulário a partir do perfil (saída de ProfileFiles.get_profile). Não depende de MCP.

Escolhe, entre as opções do formulário, a que equivale ao valor do perfil: por igualdade, por grupos de
equivalência explícitos ("Branca" = "Branco" = "White"; "Prefiro não responder" = "Não desejo informar"), por
faixas numéricas (anos de experiência, pretensão) ou pela escala de idiomas (o nível declarado, ou a certificação
quando a pergunta pede certificação ou nível CEFR; o nível mais próximo sem arredondar para cima). Sem equivalência, bloqueia com o motivo; nunca escolhe pela opção "mais parecida" nem
deduz uma resposta que o perfil não tem. Perguntas de diversidade só saem dos campos de diversidade.
"""

import math
import re
from datetime import date
from typing import Any

from vagas import diversity, experience, generic_questions, languages
from vagas.normalize import normalize_text

LANGUAGES_LABEL = languages.LANGUAGES_LABEL
CERTIFICATIONS_LABEL = languages.CERTIFICATIONS_LABEL

# Grupos de equivalência: frases (normalizadas) que querem dizer a mesma resposta. Uma opção pertence ao grupo
# quando é a frase ou começa por ela ("Não possuo deficiência" está em "Não").
NOT_SAY = ("prefiro nao responder", "prefiro nao informar", "prefiro nao dizer", "prefiro nao declarar",
           "nao desejo informar", "nao desejo responder", "nao desejo declarar", "nao quero informar",
           "nao quero responder", "nao declarar", "nao informar", "nao informado", "prefer not to say",
           "prefer not to answer", "i prefer not to say", "i prefer not to answer", "decline to answer",
           "decline to self identify", "i dont wish to answer")
GROUPS: tuple[tuple[str, ...], ...] = (
    ("sim", "yes", "possuo", "tenho deficiencia", "sou pcd", "sou pessoa com deficiencia"),
    ("nao", "no", "nenhuma", "nenhum", "nao possuo", "nao tenho", "nao sou pcd", "nao sou pessoa com deficiencia"),
    ("branca", "branco", "white"),
    ("preta", "preto", "black"),
    ("parda", "pardo"),
    ("amarela", "amarelo"),
    ("indigena", "indigenous"),
    ("homem cisgenero", "homem cis", "cisgender man", "cis man"),
    ("mulher cisgenera", "mulher cisgenero", "mulher cis", "cisgender woman", "cis woman"),
    ("homem transgenero", "homem trans", "transgender man", "trans man"),
    ("mulher transgenera", "mulher transgenero", "mulher trans", "transgender woman", "trans woman"),
    ("nao binario", "nao binarie", "non binary", "nonbinary"),
    ("heterossexual", "hetero", "heterosexual", "straight"),
    ("gay", "homossexual", "homosexual"),
    ("lesbica", "lesbian"),
    ("bissexual", "bisexual"),
    ("pansexual",),
    ("assexual", "asexual"),
    # Amplos por último: "Homem cisgênero" também responde "Homem" quando o formulário só tem Homem/Mulher.
    ("masculino", "homem", "male", "man"),
    ("feminino", "mulher", "female", "woman"),
)

_CEFR = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6}
_LEVEL_WORDS = (  # ordem importa: "intermediário avançado" antes de "intermediário" e de "avançado"
    (("intermediario avancado", "upper intermediate", "intermediario superior"), 4),
    (("nativo", "native", "lingua materna"), 7),
    (("fluente", "fluent", "proficiente", "proficient"), 6),
    (("avancado", "advanced"), 5),
    (("intermediario", "intermediate"), 3),
    (("basico", "basic", "elementar", "elementary"), 2),
    (("iniciante", "beginner"), 1),
)
# Escalas descritivas (LinkedIn, Ashby...): frases que dizem o nível sem o nome dele. Ordem importa: "full
# professional" antes de "professional working"; comparadas por palavras inteiras.
_DESCRIPTIVE = (
    (("native or bilingual", "bilingual", "native speaker", "mother tongue", "bilingue", "lingua nativa"), 7),
    (("full professional", "without limitations", "no limitations", "sem limitacoes", "sem nenhuma limitacao",
      "any situation", "qualquer situacao"), 6),
    (("professional working", "minor limitations", "pequenas limitacoes", "poucas limitacoes",
      "participate in meetings", "participar de reunioes"), 5),
    (("limited working", "familiar topics", "assuntos familiares", "simple conversations", "conversas simples"), 3),
    (("elementary proficiency", "basic words", "simple phrases", "palavras basicas", "frases simples"), 2),
    (("no proficiency", "don t speak", "dont speak", "do not speak", "nao falo", "no knowledge", "nenhum conhecimento",
      "nao tenho conhecimento"), 0),
)
_CERTIFICATION = ("certifica", "cefr", "qecr", "quadro europeu", "quadro comum europeu", "common european framework")
_YEARS = ("anos de experiencia", "tempo de experiencia", "years of experience", "experiencia em anos",
          "quantos anos")
_SALARY = ("pretensao", "expectativa salarial", "salario pretendido", "salario desejado", "remuneracao pretendida",
           "remuneracao desejada", "salary expectation", "expected salary", "desired salary")
_STOP = {"a", "o", "e", "de", "da", "do", "das", "dos", "em", "no", "na", "para", "com", "voce", "seu", "sua", "qual",
         "quais", "possui", "tem", "ja", "um", "uma", "ao", "os", "as", "your", "do", "you", "have", "the", "of", "opcoes"}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+]+", " ", normalize_text(text or "")).split())


def _is(option: str, phrase: str) -> bool:
    return option == phrase or option.startswith(phrase + " ")


def _not_say(text: str) -> bool:
    return any(_is(_norm(text), p) for p in NOT_SAY)


def _groups_of(value: str) -> list[tuple[str, ...]]:
    norm = _norm(value)
    return [g for g in GROUPS if any(_is(norm, p) for p in g)]


def pick(value: str, options: list[str]) -> str | None:
    """A opção que equivale ao valor do perfil, ou None. Sem opções, o próprio valor."""
    if not options:
        return value
    norm = _norm(value)
    if exact := [o for o in options if _norm(o) == norm]:
        return exact[0]
    if _not_say(value):
        found = [o for o in options if _not_say(o)]
        return found[0] if len(found) == 1 else None
    for group in _groups_of(value):
        found = [o for o in options if not _not_say(o) and any(_is(_norm(o), p) for p in group)]
        if len(found) == 1:
            return found[0]
        if found:
            return None  # duas opções no mesmo grupo: não escolhe
    contained = [o for o in options if len(_norm(o)) >= 3 and not _not_say(o)
                 and (_norm(o) in norm or norm in _norm(o))]
    return contained[0] if len(contained) == 1 else None


# --- faixas numéricas ------------------------------------------------------------------------------

def _number(text: str) -> float:
    """"8.001" -> 8001; "12.000,50" -> 12000.5; "3,5" -> 3.5."""
    if "," in text:
        whole, _, cents = text.rpartition(",")
        return float(whole.replace(".", "") + "." + cents)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        return float(text.replace(".", ""))
    return float(text)


def _range(option: str) -> tuple[float, float, bool] | None:
    """(mínimo, máximo, mínimo exclusivo) da opção, ou None se ela não tem número."""
    numbers = [_number(n.rstrip(".,")) for n in re.findall(r"\d[\d.,]*", option)]
    if not numbers:
        return None
    norm = _norm(option)
    low = numbers[0]
    if re.search(r"\d\s*\+", option) or "ou mais" in norm or "a partir de" in norm or "or more" in norm:
        return low, math.inf, False
    if any(w in norm for w in ("mais de", "acima de", "superior a", "more than", "over", "above")):
        return low, math.inf, True
    if any(w in norm for w in ("menos de", "abaixo de", "inferior a", "less than", "under", "below")):
        return -math.inf, low - 1e-9, False
    if norm.startswith(("ate ", "up to")):
        return -math.inf, low, False
    if len(numbers) >= 2:
        return min(numbers[:2]), max(numbers[:2]), False
    return low, low, False


def pick_number(value: float, options: list[str]) -> str | None:
    """A opção cuja faixa contém o valor; com duas (bordas iguais, "1+" e "3+"), a de mínimo maior."""
    if not options:
        return str(int(value)) if float(value).is_integer() else str(value)
    found = []
    for option in options:
        bounds = _range(option)
        if bounds is None:
            continue
        low, high, exclusive = bounds
        if (value > low if exclusive else value >= low) and value <= high:
            found.append((low, option))
    return max(found)[1] if found else None


# --- idiomas ---------------------------------------------------------------------------------------

def _has(norm: str, phrase: str) -> bool:
    return f" {phrase} " in f" {norm} "


def _level(text: str) -> int | None:
    """Posição na escala: frase descritiva, palavra de nível ("avançado") ou, sem elas, o código CEFR."""
    norm = _norm(text)
    for phrases, rank in _DESCRIPTIVE:
        if any(_has(norm, p) for p in phrases):
            return rank
    if found := next((rank for words, rank in _LEVEL_WORDS if any(w in norm for w in words)), None):
        return found
    code = languages.cefr(text)
    return _CEFR[code] if code else None


def _language_of(question: str) -> str | None:
    return languages.key(question)


# --- resolução -------------------------------------------------------------------------------------

def _fields(profile: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(s["name"], f) for s in profile.get("sections") or [] for f in s.get("fields") or []]


def _find(profile: dict[str, Any], label: str) -> tuple[str, dict[str, Any]] | None:
    key = _norm(label)
    return next(((s, f) for s, f in _fields(profile) if _norm(f["label"]) == key), None)


def _diversity_questions(question: str) -> list[diversity.Question]:
    norm = _norm(question)
    tokens = set(norm.split())
    by = {q.label: q for q in diversity.QUESTIONS}
    if "deficien" in norm or tokens & {"pcd", "pcds", "disability"}:
        return [by[diversity.DISABILITY]]
    if "orientacao" in tokens or "sexual orientation" in norm:
        return [by["Orientação sexual"]]
    if "identidade de genero" in norm or "gender identity" in norm:
        return [by["Identidade de gênero"]]
    if tokens & {"raca", "etnia", "cor", "race", "ethnicity"}:
        return [by["Cor/raça (IBGE)"]]
    if tokens & {"sexo", "sex"}:
        return [by["Sexo"]]
    if tokens & {"genero", "gender"}:
        return [by["Identidade de gênero"], by["Sexo"]]
    return []


def _blocked_by_status(section: str, field: dict[str, Any]) -> dict[str, Any] | None:
    status, label = field["status"], field["label"]
    if status == "preencher":
        return {"blocked": True, "missing_field": label, "existing": True,
                "reason": f"O campo {label!r} do perfil ainda está a preencher: pergunte ao usuário e grave com "
                          "add_profile_field (mesmo label, value)."}
    if status in ("cofre", "cofre_vazio"):
        return {"blocked": True, "reason": f"{label} é documento do cofre: quem preenche é a extensão do Chrome. "
                                           "Deixe o campo vazio."}
    if status == "manual":
        return {"blocked": True, "reason": f"{label} é dado sensível: o usuário digita no formulário."}
    if status == "migrar":
        return {"blocked": True, "reason": "As respostas de diversidade estão no formato antigo: mostre a proposta "
                                           "'migration' do get_profile ao usuário e chame apply_profile_migration."}
    return None


def _answer(section: str, field: dict[str, Any], options: list[str]) -> dict[str, Any]:
    if blocked := _blocked_by_status(section, field):
        return blocked
    chosen = pick(field["value"], options)
    if chosen is None:
        return {"blocked": True, "reason": f"Nenhuma opção do formulário equivale a {field['value']!r} (campo "
                                           f"{field['label']!r} do perfil). Opções: {', '.join(options)}."}
    return {"answer": chosen, "source": {"kind": "perfil", "field": field["label"], "section": section}}


def _missing(label: str, section: str | None) -> dict[str, Any]:
    return {"blocked": True, "missing_field": label, "existing": False, "section": section,
            "reason": f"O perfil não tem {label!r}: pergunte ao usuário uma vez e grave a resposta com "
                      "add_profile_field (mesmo label, value)."}


_GENERIC_LABELS = {_norm(label) for label in generic_questions.LABELS.values()}


def _without_options(label: str) -> str:
    return re.sub(r"\s*\bopcoes\b.*$", "", _norm(label))


def _answered_label(profile: dict[str, Any], question: str) -> tuple[str, dict[str, Any]] | None:
    """O campo já respondido cujo rótulo é a própria pergunta (sem as opções anotadas no rótulo)."""
    key = _without_options(question)
    return next(((s, f) for s, f in _fields(profile)
                 if f["status"] == "ok" and key and _without_options(f["label"]) == key), None)


def _by_label(profile: dict[str, Any], question: str) -> tuple[str, dict[str, Any]] | None:
    """O campo cujo rótulo é a pergunta: igual, ou com todas as palavras de um contidas no outro (o mais longo)."""
    words = set(_norm(question).split()) - _STOP
    if not words:
        return None
    best = None
    for section, field in _fields(profile):
        if diversity.question(field["label"]) or diversity.is_old_block(field["label"]):
            continue  # diversidade só pela pergunta reconhecida
        if _norm(field["label"]) in _GENERIC_LABELS:
            continue  # campos genéricos só pela pergunta reconhecida
        if _norm(field["label"]) == _norm(question):
            return section, field
        label_words = set(_norm(field["label"]).split()) - _STOP
        if label_words and (label_words <= words or words <= label_words):
            score = len(label_words & words)
            if best is None or score > best[0]:
                best = (score, section, field)
    return (best[1], best[2]) if best else None


def resolve(profile: dict[str, Any], question: str, options: list[str] | None = None, years: float | None = None,
            salary: float | None = None, company: str | None = None, today: date | None = None) -> dict[str, Any]:
    """{answer, source} ou {blocked: true, reason, missing_field?, existing?, section?}.

    years: anos de experiência a informar (get_profile.experience.years_to_inform); salary: pretensão da
    candidatura (salary_ask); company: a empresa da candidatura, para as perguntas sobre ela ("Você trabalha na
    empresa X?", "Foi indicado?"), comparada com get_profile.experience.periods. missing_field com existing
    false: o campo a criar no perfil (o rótulo da pergunta, com as opções vistas)."""
    options = [o.strip() for o in options or [] if o and o.strip()]
    norm = _norm(question)
    if questions := _diversity_questions(question):
        pending = next(((s, f) for s, f in _fields(profile) if f["status"] == "migrar"), None)
        if pending:  # criar o campo agora tiraria a resposta antiga da proposta de migração
            return _blocked_by_status(*pending)
        first = None
        for q in questions:
            found = _find(profile, q.label) or next(
                ((s, f) for s, f in _fields(profile) if diversity.question(f["label"]) is q), None)
            result = _answer(*found, options) if found else _missing(q.label, diversity.SECTION)
            if "answer" in result:
                return result
            first = first or result
        return first
    if (language := _language_of(question)) and (result := _language(profile, question, language, options)):
        return result
    if any(w in norm for w in _YEARS):
        if years is None:
            return {"blocked": True, "reason": "Anos de experiência não calculados: aprove o currículo geral ou "
                                               "declare 'Anos de experiência a declarar' no perfil."}
        chosen = pick_number(years, options)
        if chosen is None:
            return {"blocked": True, "reason": f"Nenhuma opção cobre {years} anos. Opções: {', '.join(options)}."}
        return {"answer": chosen, "source": {"kind": "experiencia", "field": "years_to_inform"}}
    if any(w in norm for w in _SALARY):
        if salary is None:
            return {"blocked": True, "reason": "Sem pretensão calculada para esta vaga: passe o application_id e, se "
                                               "ainda não houver, chame evaluate_salary."}
        chosen = pick_number(salary, options)
        if chosen is None:
            return {"blocked": True, "reason": f"Nenhuma opção cobre a pretensão {salary:g}. Opções: {', '.join(options)}."}
        return {"answer": chosen, "source": {"kind": "pretensao", "field": "salary_ask"}}
    if found := _answered_label(profile, question):
        return _answer(*found, options)
    if (result := _generic(profile, question, options, company, today or date.today())) is not None:
        return result
    if found := _by_label(profile, question):
        return _answer(*found, options)
    # Sem ":" no rótulo: no perfil, "- rótulo: valor" separa no primeiro ":".
    label = " ".join(question.strip().rstrip("*:").replace(":", " -").split())
    if options:
        label = f"{label} (opções {', '.join(o.replace(':', ' -') for o in options)})"
    return _missing(label, None)


# --- perguntas sobre a empresa da vaga -------------------------------------------------------------

def _english(question: str) -> bool:
    return bool(set(_norm(question).split()) & {"you", "your", "are", "have", "were", "did", "do", "what", "which",
                                                 "the", "is", "current", "present", "company", "employer", "title",
                                                 "job", "role", "position", "salary", "compensation", "pay", "last",
                                                 "latest", "previous", "most", "recent"})


def _yes_no(value: str, question: str, options: list[str]) -> str | None:
    """"Sim"/"Não" na opção do formulário; sem opções, na língua da pergunta."""
    if not options and _english(question):
        return {"Sim": "Yes", "Não": "No"}[value]
    return pick(value, options)


def _is_yes_no(options: list[str]) -> bool:
    return bool(options) and pick("Sim", options) is not None and pick("Não", options) is not None


def _generic(profile: dict[str, Any], question: str, options: list[str], company: str | None,
             today: date) -> dict[str, Any] | None:
    """Perguntas que repetem o nome de cada empresa: pelo currículo geral (trabalha ou trabalhou lá) ou pelo campo
    genérico de indicação. None quando a pergunta não é uma delas."""
    kind = generic_questions.kind(question, company)
    if kind is None:
        return None
    if kind in generic_questions.JOB_KINDS:
        return _current_job(profile, kind, question, options, today)
    label = generic_questions.LABELS[kind]
    if kind == generic_questions.REFERRAL:
        return _referral(profile, question, options)
    if company is None and generic_questions.points_here(question):
        return {"blocked": True, "reason": "A pergunta é sobre a empresa da vaga: chame de novo com o application_id."}
    periods = (profile.get("experience") or {}).get("periods") or []
    if not periods:
        return {"blocked": True, "reason": "Sem experiências no currículo geral aprovado para comparar com a empresa "
                                           "da vaga: aprove o currículo geral (approve_master)."}
    found = generic_questions.worked_at(periods, question, company, kind == generic_questions.CURRENT, today)
    chosen = _yes_no("Sim" if found else "Não", question, options)
    if chosen is None:
        return {"blocked": True, "reason": f"Nenhuma opção do formulário equivale a {'Sim' if found else 'Não'!r} "
                                           f"({label}). Opções: {', '.join(options)}."}
    source = {"kind": "curriculo", "field": label,
              "experiences": [f"{p.get('title')} — {p.get('company')}" for p in found]}
    return {"answer": chosen, "source": source}


def _join(items: list[str], english: bool) -> str:
    unique = list(dict.fromkeys(i for i in items if i))
    return (" and " if english else " e ").join(unique)


def _last_job_note(job: dict[str, Any], english: bool, today: date, extra: str | None = None) -> str:
    """"(PJ, último emprego, até set/2025)"; com emprego atual, só o extra."""
    parts = [extra] if extra else []
    if job["roles"] and not job["current"]:
        until = experience.month_label(job["end"], today, "en" if english else "pt")
        parts.append(("last job" if english else "último emprego") + (f", until {until}" if english and until else
                                                                       f", até {until}" if until else ""))
    return f" ({', '.join(parts)})" if parts else ""


def _current_job(profile: dict[str, Any], kind: str, question: str, options: list[str],
                 today: date) -> dict[str, Any]:
    """Empresa, cargo ou salário atuais: a experiência em andamento ou, sem nenhuma, a de término mais recente
    (empatadas: as mais longas primeiro, títulos juntos). O salário vem de "Valor da última remuneração"."""
    periods = (profile.get("experience") or {}).get("periods") or []
    job = experience.latest_roles(periods, today)
    english = _english(question)
    source = {"kind": "curriculo", "field": "experience", "current": job["current"],
              "experiences": [f"{p.get('title')} — {p.get('company')}" for p in job["roles"]]}
    if kind == generic_questions.SALARY_NOW:  # o valor vem do perfil; o currículo só diz se é o último emprego
        return _last_pay(profile, job, options, english, today, source)
    if not job["roles"]:
        return {"blocked": True, "reason": "Sem experiências no currículo geral aprovado: aprove o currículo geral "
                                           "(approve_master) para responder empresa e cargo atuais."}
    field = "company" if kind == generic_questions.COMPANY_NOW else "title"
    value = _join([p.get(field) or "" for p in job["roles"]], english)
    if options:
        chosen = pick(value, options)
        if chosen is None:
            return {"blocked": True, "reason": f"Nenhuma opção do formulário equivale a {value!r}. "
                                               f"Opções: {', '.join(options)}."}
        return {"answer": chosen, "source": source}
    return {"answer": value + _last_job_note(job, english, today), "source": source}


def _last_pay(profile: dict[str, Any], job: dict[str, Any], options: list[str], english: bool, today: date,
              job_source: dict[str, Any]) -> dict[str, Any]:
    label = generic_questions.LAST_PAY_LABEL
    found = _find(profile, label)
    if found is None:
        return _missing(label, generic_questions.SECTION)
    section, field = found
    if blocked := _blocked_by_status(section, field):
        return blocked
    numbers = re.findall(r"\d[\d.,]*", field["value"])
    if not numbers:
        return {"blocked": True, "reason": f"O campo {label!r} do perfil não tem um valor: peça ao usuário o valor "
                                           "mensal e o regime (ex.: 10500, PJ) e grave com add_profile_field."}
    amount = _number(numbers[0].rstrip(".,"))
    amount = int(amount) if float(amount).is_integer() else amount
    regime = next((w.upper() for w in _norm(field["value"]).split() if w in ("pj", "clt")), None)
    source = {"kind": "perfil", "field": label, "section": section, "current": job_source["current"],
              "experiences": job_source["experiences"]}
    if options:
        chosen = pick_number(amount, options)
        if chosen is None:
            return {"blocked": True, "reason": f"Nenhuma opção cobre {amount:g} ({label}). Opções: {', '.join(options)}."}
        return {"answer": chosen, "number": amount, "source": source}
    whole = f"{amount:,.0f}" if isinstance(amount, int) else f"{amount:,.2f}"
    money = f"R$ {whole}" if english else "R$ " + whole.replace(",", "X").replace(".", ",").replace("X", ".")
    money += " per month" if english else " mensais"
    return {"answer": money + _last_job_note(job, english, today, regime), "number": amount, "source": source}


def _referral(profile: dict[str, Any], question: str, options: list[str]) -> dict[str, Any]:
    label = generic_questions.REFERRAL_LABEL
    found = _find(profile, label)
    if found is None:
        return _missing(label, generic_questions.SECTION)
    section, field = found
    if blocked := _blocked_by_status(section, field):
        return blocked
    if generic_questions.asks_details(question) and not _is_yes_no(options):
        if pick(field["value"], ["Sim", "Não"]) == "Não":
            return {"blocked": True, "reason": f"O perfil diz que não houve indicação ({label!r}): deixe o campo em "
                                               "branco; se for obrigatório, pergunte ao usuário."}
        return {"blocked": True, "reason": "A pergunta pede o nome ou o contato de quem indicou: pergunte ao usuário."}
    value = pick(field["value"], ["Sim", "Não"])
    if value is None:
        return _answer(section, field, options)
    chosen = _yes_no(value, question, options)
    if chosen is None:
        return {"blocked": True, "reason": f"Nenhuma opção do formulário equivale a {field['value']!r} (campo "
                                           f"{label!r} do perfil). Opções: {', '.join(options)}."}
    return {"answer": chosen, "source": {"kind": "perfil", "field": label, "section": section}}


def _language(profile: dict[str, Any], question: str, language: str, options: list[str]) -> dict[str, Any] | None:
    """Pergunta de idioma: o nível declarado em "Idiomas"; a certificação quando a pergunta pede certificação ou as
    opções são níveis CEFR. None quando o perfil não responde (a pergunta segue para os outros campos)."""
    found = {label: _find(profile, label) for label in (LANGUAGES_LABEL, CERTIFICATIONS_LABEL)}
    values = {label: f[1]["value"] if f and f[1]["status"] == "ok" else None for label, f in found.items()}
    row = languages.levels(values[LANGUAGES_LABEL], values[CERTIFICATIONS_LABEL]).get(language) or {}
    norm = _norm(question)
    asks = any(w in norm for w in _CERTIFICATION)
    scale = [o for o in options if not _not_say(o)]
    cefr_scale = bool(scale) and all(languages.cefr(o) for o in scale)
    if asks or cefr_scale:
        label = CERTIFICATIONS_LABEL if found[CERTIFICATIONS_LABEL] or not row.get("certification") else LANGUAGES_LABEL
        source = {"kind": "perfil", "field": label, "section": (found[label] or ("",))[0]}
        if row.get("certification"):
            if asks and scale and not any(_level(o) is not None for o in scale):
                chosen = pick("Sim", options)  # "Possui certificação de inglês?": sim/não
                return {"answer": chosen, "source": source} if chosen else None
            return _by_rank(row["certification"], options, source)
        if asks and values[CERTIFICATIONS_LABEL] is not None:  # o campo lista as certificações, e esta não está
            chosen = pick("Não", options) if scale else None
            if chosen:
                return {"answer": chosen, "source": source}
            return {"blocked": True, "reason": f"O perfil não tem certificação de {row.get('name') or language} "
                                               f"(campo {CERTIFICATIONS_LABEL!r}): pergunte ao usuário."}
        if asks:
            return None
    level = row.get("declared") or row.get("certification")
    if level is None:
        return None
    source = {"kind": "perfil", "field": LANGUAGES_LABEL, "section": found[LANGUAGES_LABEL][0]}
    return _by_rank(level, options, source)


def _by_rank(level: str, options: list[str], source: dict[str, Any]) -> dict[str, Any] | None:
    """A opção da escala mais próxima do nível sem arredondar para cima. Sem opções, o próprio nível. None quando
    nenhuma opção é nível (não é escala); bloqueia quando a escala tem opção que não se lê ou empate."""
    if not options:
        return {"answer": level, "source": source}
    scale = [o for o in options if not _not_say(o)]
    ranked = [(_level(o), o) for o in scale]
    if all(rank is None for rank, _ in ranked):
        return None
    if unknown := [o for rank, o in ranked if rank is None]:
        return {"blocked": True, "reason": f"Não sei onde fica {unknown[0]!r} na escala de idiomas: pergunte ao "
                                           f"usuário. Opções: {', '.join(options)}."}
    mine = _level(level)
    fitting = [(rank, o) for rank, o in ranked if mine is not None and rank <= mine]
    if not fitting:
        return {"blocked": True, "reason": f"Nenhuma opção cabe no nível {level!r} sem arredondar para cima. "
                                           f"Opções: {', '.join(options)}."}
    best = max(rank for rank, _ in fitting)
    tied = [o for rank, o in fitting if rank == best]
    if len(tied) > 1:
        return {"blocked": True, "reason": f"Mais de uma opção equivale ao nível {level!r}: {', '.join(tied)}. "
                                           "Pergunte ao usuário."}
    return {"answer": tied[0], "source": source}
