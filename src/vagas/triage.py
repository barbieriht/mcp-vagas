"""Triagem de uma vaga numa chamada: duplicata, leitura, critérios fixos, aderência, registro e salário.

Não depende de MCP. Os critérios fixos vêm de um arquivo pessoal (criterios-triagem.md), no formato:

    - Cargos alvo: data_scientist, ml_engineer, ai_engineer
    - Cargos condicionados à aderência: data_engineer, data_analyst
    - Aderência mínima: 50
    - Empresas ignoradas: Empresa X, Empresa Y
    - Termos de vaga exclusiva PcD: exclusiva para PcD, vaga afirmativa para PcD
    - Vagas afirmativas que posso disputar: mulheres, pessoas negras, LGBTQIA+, PcD, 50+, indígenas, ou nenhuma
    - Locais aceitos para híbrido e presencial: SP: São Paulo, São Carlos; MG:

O que as regras não decidem vira um item em "needs", para a LLM julgar ou pesquisar.
"""

import hashlib
import os
import re
import sqlite3
from datetime import datetime
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from vagas import affirmative
from vagas.db import default_db_path
from vagas.job_posting import Fetcher, JobPostingError, http_fetch, read_job_posting
from vagas import roles as roles_
from vagas.models import CURRENCIES, SENIORITIES
from vagas.normalize import normalize_company, normalize_text
from vagas.places import PlaceGroup, parse_places, state_code, state_of
from vagas.repo import Repo, VagasError
from vagas.resume_repo import ResumeStore, default_draft_path
from vagas.experience import experience_years
from vagas.salary import SalaryStore, _city
from vagas.salary_policy import default_policy_path

_ITEM = re.compile(r"^\s{0,1}[-*]\s+(?P<key>[^:]+?)\s*:\s*(?P<value>.*?)\s*$")
_MODE_LABELS = {"hibrido": "híbrida", "presencial": "presencial"}
# Termos que marcam vaga exclusiva para PcD: conhecimento da ferramenta, não configuração do usuário.
# A linha "Termos de vaga exclusiva PcD" dos critérios, se existir, só acrescenta termos a estes.
DEFAULT_PCD_TERMS: tuple[str, ...] = (
    "exclusiva para pcd", "exclusiva pcd", "exclusivo para pcd", "exclusiva para pcds", "exclusiva a pcd",
    "exclusiva para pessoas com deficiencia", "exclusivo para pessoas com deficiencia",
    "vaga afirmativa para pcd", "vaga destinada a pcd", "vaga destinada a pessoas com deficiencia",
    "somente para pcd", "apenas para pcd",
)
_KEYS = {
    "cargos alvo": "target_roles",
    "cargos condicionados a aderencia": "conditional_roles",
    "aderencia minima": "min_match",
    "empresas ignoradas": "ignored_companies",
    "termos de vaga exclusiva pcd": "pcd_terms",
    "vagas afirmativas que posso disputar": "affirmative_ok",
    "locais aceitos para hibrido e presencial": "accepted_locations",
    "senioridades buscadas": "search_seniorities",
    "senioridades a que me candidato": "search_seniorities",
    "anos por senioridade": "years_by_level",
    "niveis de experiencia": "years_by_level",
    "estados aceitos para hibrido e presencial": "accepted_states",
}
@dataclass(frozen=True)
class Level:
    """Nível de experiência: anos aproximados (max None = sem teto). Faixas vizinhas podem se sobrepor."""
    name: str
    min: int
    max: int | None = None

    def years(self) -> str:
        return f"{self.min}–{self.max}" if self.max is not None else f"{self.min}+"


# Tabela de referência (editável em "Níveis de experiência" no criterios-triagem.md):
# júnior 0–2 (competências fundamentais), pleno 2–5 (autonomia na execução), sênior 5–8 (liderança
# técnica), especialista 7–12+ (referência num domínio), staff/principal 10–15+ (influência arquitetural).
DEFAULT_LEVELS = (Level("junior", 0, 2), Level("pleno", 2, 5), Level("senior", 5, 8), Level("especialista", 7, 12),
                  Level("staff", 10, 15))
MAX_YEARS_REQUIRED = 15  # acima disso é história da empresa ("for over 50 years"), não requisito
_YEARS = re.compile(
    r"(?:(?:at least|minimum of|mínimo de|minimo de|pelo menos|mais de|over)\s+)?"
    r"(\d{1,2})\s*(?:\+|(?:a|to|-|–)\s*\d{1,2})?\s*(?:anos|years?|yrs)\b", re.I)


@dataclass(frozen=True)
class TriageCriteria:
    target_roles: tuple[str, ...]  # chaves dos cargos (roles_.Role.key)
    conditional_roles: tuple[str, ...] = ()
    roles: tuple[roles_.Role, ...] = ()  # os cargos dos critérios, com nomes e sinônimos
    min_match: int = 50
    ignored_companies: tuple[str, ...] = ()  # normalizados como empresa
    pcd_terms: tuple[str, ...] = ()  # normalizados como texto
    affirmative_ok: tuple[str, ...] = ()  # grupos (affirmative.GROUPS) cujas vagas afirmativas o usuário disputa
    places: tuple[PlaceGroup, ...] = ()  # locais aceitos para híbrido e presencial, por estado
    location_names: tuple[str, ...] = ()  # cidades aceitas como escritas, para as buscas
    search_seniorities: tuple[str, ...] = ()  # buscas e níveis a que o usuário se candidata (vazio = todos)
    years_by_level: tuple[Level, ...] = DEFAULT_LEVELS  # anos de experiência -> nível
    accepted_states: tuple[str, ...] = ()  # UFs dos grupos de locais (e da linha antiga); vazio = não filtra


_CRITERIA_STATE = "triage_criteria_sha256"
_PROFILE_SAYS = {
    "nao": "; o perfil diz \"Possui deficiência: não\" (vale mais que PcD nos critérios).",
    "nao_informado": "; o perfil diz \"Possui deficiência: prefiro não responder\" (vale mais que PcD nos critérios).",
    "pendente": "; \"Possui deficiência\" ainda está a preencher no perfil.",
}


def _with_disability(criteria: "TriageCriteria", answer: str | None) -> "TriageCriteria":
    """PcD entre os grupos disputados só com "Possui deficiência: sim"; sem o campo no perfil, vale o critério."""
    if answer is None:
        return criteria
    groups = tuple(g for g in criteria.affirmative_ok if g != "pcd") + (("pcd",) if answer == "sim" else ())
    return replace(criteria, affirmative_ok=groups)
_OPEN = ("a_aplicar", "pendente_usuario")
RECHECK_NOTE = "Descartada porque os critérios de triagem mudaram."


def default_criteria_path(db_path: Path | str | None = None) -> Path:
    if env := os.environ.get("VAGAS_TRIAGE_CRITERIA"):
        return Path(env)
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / "criterios-triagem.md"


def load_criteria(path: Path | str) -> TriageCriteria:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise VagasError(
            f"Critérios de triagem não encontrados em {path}. Crie o arquivo ou aponte VAGAS_TRIAGE_CRITERIA "
            "para ele (modelo: skill/candidaturas/criterios-triagem.example.md), ou faça a triagem manual."
        ) from None
    return parse_criteria(text, source=path.name)


def _clean(text: str) -> str:
    """Sem espaços nas pontas nem pontuação final ("Sênior." -> "Sênior")."""
    return text.strip().rstrip(".;").strip()


def _roles(value: str) -> tuple[roles_.Role, ...]:
    """Cargos em texto livre ("Desenvolvedor Backend", "Product Manager (PM, Gerente de Produto)"); códigos e nomes
    das famílias conhecidas ("data_scientist", "cientista de dados") valem como sempre."""
    return roles_.parse_list(value)


def parse_criteria(text: str, source: str = "criterios-triagem.md") -> TriageCriteria:
    values: dict[str, Any] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        where = f"{source}, linha {number}"
        if line.startswith("## Valores aceitos"):
            break  # documentação dos campos, não critérios
        if "<PREENCHER" in line:
            raise VagasError(f"Preencha o campo em {where}: {line.strip()}")
        item = _ITEM.match(line)
        if not item or (field := _KEYS.get(normalize_text(item["key"]))) is None:
            continue
        value = _clean(item["value"])
        if not value:
            continue  # campo vazio vale o padrão, como sem a linha
        items = [_clean(v) for v in value.split(",") if _clean(v)]
        if field in ("target_roles", "conditional_roles"):
            found = _roles(value)
            values[field] = tuple(r.key for r in found)
            values["roles"] = (*values.get("roles", ()), *(r for r in found if r.key not in
                                                          {x.key for x in values.get("roles", ())}))
        elif field == "min_match":
            number = value.rstrip("%").strip()
            if not number.isdigit() or not 0 <= int(number) <= 100:
                raise VagasError(f"'Aderência mínima' inválida em {where}: {value!r} (número de 0 a 100).")
            values[field] = int(number)
        elif field == "ignored_companies":
            values[field] = tuple(normalize_company(v) for v in items)
        elif field == "search_seniorities":
            levels = [normalize_text(v) for v in items]  # "Sênior" -> "senior"
            unknown = [v for v, level in zip(items, levels) if level not in SENIORITIES]
            if unknown:
                raise VagasError(f"Senioridade desconhecida em {where}: {', '.join(unknown)}. Valores aceitos: "
                                 f"{', '.join(SENIORITIES)} (maiúsculas e acentos são ignorados).")
            values[field] = tuple(dict.fromkeys(levels))
        elif field == "affirmative_ok":
            values[field] = affirmative.parse_groups(items, where)
        elif field == "years_by_level":
            values[field] = _years_by_level(items, where)
        elif field == "accepted_states":
            values[field] = tuple(_state(v, where) for v in items)
        elif field == "accepted_locations":
            values["places"] = parse_places(value, where)
            values["location_names"] = tuple(dict.fromkeys(c for g in values["places"] for c in g.cities))
        else:
            values[field] = tuple(normalize_text(v) for v in items)
    if not values.get("target_roles"):
        raise VagasError(f"{source}: informe os cargos alvo ('- Cargos alvo: <cargo>, <cargo>'). Sugestões do seu "
                         "currículo geral: suggest_target_roles, ou a seção de critérios do painel.")
    # Os estados dos grupos de locais são os aceitos; a linha antiga "Estados aceitos" ainda soma a eles.
    states = [g.state for g in values.get("places", ()) if g.state] + list(values.get("accepted_states", ()))
    values["accepted_states"] = tuple(dict.fromkeys(states))
    return TriageCriteria(**values)


_REF = re.compile(r"\bref\s*#?\s*(\d+)", re.I)
_STOPWORDS = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "para", "com", "and", "of", "the", "in"}


def _title_terms(title: str) -> set[str]:
    base = re.split(r"\s+[|–—-]\s+|\s*\|", title)[0]
    return set(re.findall(r"[a-z0-9]+", normalize_text(base))) - _STOPWORDS


def _same_title(a: str, b: str) -> bool:
    """Títulos equivalentes: mesmos termos (Jaccard >= 0,8) e, se ambos tiverem código REF#, o mesmo código."""
    refs = _REF.search(a), _REF.search(b)
    if all(refs) and refs[0].group(1) != refs[1].group(1):
        return False
    ta, tb = _title_terms(a), _title_terms(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.8


def _same_place(a: str | None, b: str | None) -> bool:
    """Mesma cidade, ou uma das vagas sem cidade (Brasil, remoto)."""
    ca, cb = _city(a), _city(b)
    return ca is None or cb is None or normalize_text(ca) == normalize_text(cb)


def _years_by_level(items: list[str], where: str) -> tuple[Level, ...]:
    """"pleno 2-5", "pleno 2 a 5", "especialista 7-12+", "staff 10+" ou só o mínimo, "pleno 3"."""
    found = []
    for item in items:
        text = normalize_text(re.sub(r"[–—]", "-", item))  # normalize_text descarta o travessão
        match = re.fullmatch(r"(\w+)\s+(\d{1,2})\s*(?:(?:-|a|ate)\s*(\d{1,2}))?\s*\+?", text)
        if not match:
            raise VagasError(f"'Níveis de experiência' inválido em {where}: {item!r} (ex.: 'pleno 2-5').")
        if match[1] not in SENIORITIES:
            raise VagasError(f"Senioridade desconhecida em {where}: {match[1]}. Valores aceitos: "
                             f"{', '.join(SENIORITIES)}.")
        low, high = int(match[2]), int(match[3]) if match[3] else None
        if high is not None and high < low:
            raise VagasError(f"'Níveis de experiência' inválido em {where}: {item!r} (o máximo, {high}, é menor "
                             f"que o mínimo, {low}; ex.: 'pleno 2-5').")
        found.append(Level(match[1], low, high))
    return tuple(sorted(found, key=lambda level: level.min))


def _state(value: str, where: str) -> str:
    if (uf := state_code(value)) is None:
        raise VagasError(f"Estado desconhecido em {where}: {value!r}. Use a sigla (ex.: SP) ou o nome do estado.")
    return uf


def years_required(text: str | None) -> int | None:
    """Anos de experiência pedidos na descrição (o menor de uma faixa), só perto de "experiência"."""
    text = text or ""
    for match in _YEARS.finditer(text):
        start = max(text.rfind(c, 0, match.start()) for c in ".!?;\n•") + 1
        ends = [i for i in (text.find(c, match.end()) for c in ".!?;\n•") if i >= 0]
        sentence = normalize_text(text[start:min(ends) if ends else len(text)])
        if "experien" in sentence and int(match.group(1)) <= MAX_YEARS_REQUIRED:
            return int(match.group(1))
    return None


def level_for_years(years: float, table: tuple[Level, ...]) -> str:
    """Maior nível cujo mínimo de anos cabe nos anos dados (abaixo de todos: o primeiro)."""
    eligible = [level.name for level in table if years >= level.min]
    return eligible[-1] if eligible else table[0].name


def _contains(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


class Triage:
    def __init__(
        self,
        conn: sqlite3.Connection,
        fetcher: Fetcher = http_fetch,
        criteria_path: Path | str | None = None,
        policy_path: Path | str | None = None,
        draft_path: Path | str | None = None,
        salary_rule: str = "teto",
        disability: Callable[[], str | None] | None = None,
    ):
        """disability: resposta de "Possui deficiência" do perfil (profile_fields.disability_answer). Ela decide
        as vagas exclusivas e afirmativas PcD no lugar de "PcD" nos critérios: só "sim" disputa; sem o campo
        (None), vale o critério."""
        self.repo = Repo(conn)
        self.disability = disability
        self.resumes = ResumeStore(conn, draft_path or default_draft_path())
        self.salaries = SalaryStore(conn, policy_path=policy_path or default_policy_path(), rule=salary_rule)
        self.fetcher = fetcher
        self.criteria_path = Path(criteria_path) if criteria_path is not None else default_criteria_path()

    def triage_job(self, url: str, search_id: int | None = None, not_duplicate: bool = False) -> dict[str, Any]:
        recheck = self.apply_criteria_changes()
        result = self._triage_job(url, search_id, not_duplicate)
        if recheck and recheck["discarded"]:
            result["criteria_recheck"] = recheck
        return result

    def apply_criteria_changes(self) -> dict[str, Any] | None:
        """Se o criterios-triagem.md mudou desde a última conferência (pelo painel ou à mão), confere de novo as
        vagas abertas (a_aplicar, pendente_usuario) pelas regras que não pedem julgamento: empresas ignoradas,
        vagas PcD e afirmativas fora dos grupos, senioridades buscadas e estados aceitos. As reprovadas viram
        descartadas, com o motivo da triagem. Critérios iguais: None, e uma vaga reaberta à mão continua aberta.
        Sem arquivo de critérios: None. Retorna {checked, discarded: [{id, company, role, url, reason}]}."""
        try:
            text = self.criteria_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        answer = self.disability() if self.disability else None
        key = text if answer is None else f"{text}\n\0possui deficiencia={answer}"
        fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if self.repo.get_state(_CRITERIA_STATE) == fingerprint:
            return None
        criteria = _with_disability(parse_criteria(text, source=self.criteria_path.name), answer)
        open_apps = [app for status in _OPEN for app in self.repo.list_applications(status=status)["applications"]]
        discarded = []
        for app in open_apps:
            reason = self._recheck(criteria, app, answer)
            if reason:
                self.repo.update_application(app["id"], status="descartada", discard_reason=reason, note=RECHECK_NOTE)
                discarded.append({"id": app["id"], "company": app["company"], "role": app["role"], "url": app["url"],
                                  "reason": reason})
        self.repo.set_state(_CRITERIA_STATE, fingerprint)
        return {"checked": len(open_apps), "discarded": discarded}

    def _recheck(self, criteria: TriageCriteria, app: dict[str, Any], answer: str | None) -> str | None:
        """As mesmas regras fixas da triagem, sobre o que ficou gravado da vaga."""
        posting = {"company": app["company"], "title": app["role"], "description": app.get("description"),
                   "work_mode": app.get("work_mode"), "location": app.get("location"), "work_mode_inferred": False}
        reason = self._fixed_criteria(criteria, posting, [], answer)
        if reason is None and (level := self._level_fit(criteria, app.get("seniority"))):
            reason = self._level(criteria, level, [])
        if reason is None and posting["work_mode"] in ("hibrido", "presencial"):
            reason = self._location(criteria, posting, [], [])
        return reason

    def _triage_job(self, url: str, search_id: int | None, not_duplicate: bool) -> dict[str, Any]:
        answer = self.disability() if self.disability else None
        criteria = _with_disability(load_criteria(self.criteria_path), answer)
        existing = self.repo.find_application(url=url)  # só URL: casa pela forma canônica
        if existing:
            return self._result("ja_registrada", existing[0], None, None, None,
                                [f"Vaga já registrada com status {existing[0]['status']!r}."], [])
        try:
            posting = read_job_posting(url, fetcher=self.fetcher)
        except JobPostingError as exc:
            raise VagasError(f"{exc} Depois, faça a triagem pelos passos manuais da Skill.") from exc
        role = roles_.classify(posting["title"], criteria.roles)  # os cargos do usuário, depois os conhecidos
        posting = {**posting, "role_key": role.key if role else "outro", "role_certain": role is not None}

        if posting.get("closed"):  # nada é registrado: vaga que não aceita candidaturas não entra na lista
            return self._result("encerrada", None, posting, None, None,
                                ["A vaga não aceita candidaturas (o LinkedIn avisa que foi encerrada); "
                                 "não foi registrada."], [])

        reasons: list[str] = []
        needs: list[dict[str, Any]] = []
        if posting["seniority"] is None and (years := years_required(posting["description"])) is not None:
            posting = {**posting, "seniority": level_for_years(years, criteria.years_by_level)}
            reasons.append(f"Senioridade {posting['seniority']} pelos {years} anos de experiência pedidos na vaga.")
        title, company = posting["title"], posting["company"]
        role_key, seniority = posting["role_key"], posting["seniority"]

        if not not_duplicate:
            similar = self._similar(posting)
            if similar:
                return self._result("possivel_duplicata", None, posting, None, None, [], [{
                    "kind": "possivel_duplicata",
                    "detail": f"{company} já tem vaga registrada com o mesmo cargo e senioridade, talvez a mesma "
                              "vaga em outra plataforma. Pergunte ao usuário; se for outra vaga, chame triage_job "
                              "de novo com not_duplicate=true.",
                    "matches": similar,
                }])

        discard = self._fixed_criteria(criteria, posting, reasons, answer)
        if discard is None and affirmative.detect(f"{title}. {posting['description'] or ''}").generic:
            needs.append({"kind": "afirmativa", "detail": "A vaga se diz afirmativa, mas não cita um grupo "
                          "reconhecido. Leia a descrição: se for para um grupo fora de 'Vagas afirmativas que "
                          "posso disputar', chame update_application com status \"descartada\" e discard_reason."})
        match = None
        if discard is None:
            match = self._match(posting, needs)
            discard = self._role(criteria, posting, match, reasons, needs)
        if discard is None:
            discard = self._location(criteria, posting, reasons, needs)
        level = self._level_fit(criteria, seniority)
        if discard is None and level:
            discard = self._level(criteria, level, reasons)

        app = self.repo.add_application(
            company=company or "(empresa não informada)", role=title, source=posting["source"], url=url,
            seniority=seniority, work_mode=posting["work_mode"], location=posting["location"],
            description=posting["description"] or None, status="descartada" if discard else "a_aplicar",
            discard_reason=discard, search_id=search_id, contract=posting["contract"],
            match_score=match["score"] if match else None,
            match_terms={"matched": match["matched"], "missing": match["missing"]} if match else None,
        )["application"]
        if discard:
            return self._result("descartada", app, posting, match, None, [*reasons, discard], [], level)

        salary = self._salary(app, posting, needs)
        decision = "a_aplicar"
        if salary and salary["decision"] == "nao_aplicar":
            self.repo.update_application(app["id"], status="descartada", discard_reason=salary["reason"])
            decision = "descartada"
            reasons.append(salary["reason"])
            needs = [n for n in needs if n["kind"] not in ("pesquisa_salarial", "salario")]
        elif salary:
            reasons.append(salary["reason"])
        if decision == "a_aplicar" and (referral := self._referral(app)):
            reasons.append(referral)
        if needs:
            self.repo.set_needs(app["id"], needs)  # consultável depois (query_applications needs_any)
        return self._result(decision, self.repo.get(app["id"]), posting, match, salary, reasons, needs, level)

    # --- Etapas ---------------------------------------------------------------------------------

    def _referral(self, app: dict[str, Any]) -> str | None:
        """Motivo da indicação na empresa (só nomes e área: o contato de quem indicou não sai aqui)."""
        from vagas.referrals import ReferralStore

        found = ReferralStore(self.repo.conn).for_application(app)
        if found["fits"]:
            names = ", ".join(r["name"] for r in found["fits"])
            return (f"Indicação na empresa: {names}. A vaga vem primeiro na lista de trabalho; a aderência não "
                    "muda.")
        if found["other_scope"]:
            names = ", ".join(f"{r['name']} ({r['scope']})" for r in found["other_scope"])
            return (f"Há indicação na empresa para outra área: {names}. Confirme com o usuário se vale para "
                    "esta vaga.")
        return None

    def _similar(self, posting: dict[str, Any]) -> list[dict[str, Any]]:
        """Vagas da mesma empresa que podem ser esta, publicada em outra plataforma: título equivalente
        e local compatível. Mesmo título em outra cidade, ou outro código de vaga (REF#), é outra vaga."""
        company = posting["company"]
        if not company:
            return []
        similar = []
        for app in self.repo.find_application(company=company):
            if _same_title(app["role"], posting["title"]) and _same_place(app["location"], posting["location"]):
                similar.append({k: app[k] for k in ("id", "company", "role", "location", "source", "url", "status")})
        return similar

    @staticmethod
    def _fixed_criteria(criteria: TriageCriteria, posting: dict[str, Any], reasons: list[str],
                        disability: str | None = None) -> str | None:
        company = posting["company"] or ""
        if company and normalize_company(company) in criteria.ignored_companies:
            return f"Empresa {company} está na lista de empresas ignoradas."
        text = normalize_text(f"{posting['title']} {posting['description'] or ''}")
        term = next((t for t in (*DEFAULT_PCD_TERMS, *criteria.pcd_terms) if _contains(text, t)), None)
        if term and "pcd" not in criteria.affirmative_ok:
            return f"Vaga exclusiva para PcD (termo {term!r} na vaga)" + _PROFILE_SAYS.get(disability, ".")
        found = affirmative.detect(f"{posting['title']}. {posting['description'] or ''}")
        blocked = [g for g in found.groups if g not in criteria.affirmative_ok]
        if blocked == ["pcd"] and disability is not None:
            return f"Vaga afirmativa para PcD (\"{found.snippets['pcd']}\")" + _PROFILE_SAYS[disability]
        if blocked:
            return (f"Vaga afirmativa para {affirmative.labels(blocked)} (\"{found.snippets[blocked[0]]}\"); "
                    "não está em 'Vagas afirmativas que posso disputar' dos critérios.")
        reasons.append("Empresa fora da lista de ignoradas e sem vaga afirmativa fora dos seus grupos.")
        return None

    def _match(self, posting: dict[str, Any], needs: list[dict[str, Any]]) -> dict[str, Any] | None:
        try:
            match = self.resumes.score_job_match(posting["description"] or "", company=posting["company"],
                                                 title=posting["title"], location=posting["location"])
        except VagasError as exc:
            needs.append({"kind": "aderencia", "detail": f"Aderência não calculada: {exc}"})
            return None
        if match["score"] is None:
            needs.append({"kind": "aderencia", "detail": match["note"]})
        return match

    @staticmethod
    def _role(criteria: TriageCriteria, posting: dict[str, Any], match: dict[str, Any] | None,
              reasons: list[str], needs: list[dict[str, Any]]) -> str | None:
        role_key, title = posting["role_key"], posting["title"]
        name = roles_.names(role_key, criteria.roles)[0]
        if not posting["role_certain"]:
            listed = [roles_.names(k, criteria.roles)[0] for k in criteria.target_roles + criteria.conditional_roles]
            needs.insert(0, {"kind": "cargo", "detail": (
                f"Cargo {title!r} não reconhecido pelo título. Confirme pela descrição se é um dos cargos alvo "
                f"({', '.join(listed)}); se não for, descarte com update_application. Se for, avalie o salário com "
                "evaluate_salary (role_key do cargo, como em suggest_target_roles, e senioridade).")})
            return None
        if role_key in criteria.target_roles:
            reasons.append(f"Cargo {name} ({role_key}) entre os cargos alvo.")
            return None
        if role_key in criteria.conditional_roles:
            score = match["score"] if match else None
            if score is None:
                needs.append({"kind": "aderencia", "detail": (
                    f"Cargo {name} só entra com aderência de {criteria.min_match} ou mais, e a aderência não "
                    "foi calculada: julgue pela descrição e descarte com update_application se for baixa.")})
                return None
            if score < criteria.min_match:
                return f"Cargo {name} exige aderência de {criteria.min_match} ou mais; aderência {score}."
            reasons.append(f"Cargo {name} com aderência {score} (mínimo {criteria.min_match}).")
            return None
        return f"Cargo {name} ({role_key}) fora dos cargos alvo."

    @staticmethod
    def _location(criteria: TriageCriteria, posting: dict[str, Any], reasons: list[str],
                  needs: list[dict[str, Any]]) -> str | None:
        mode, location = posting["work_mode"], posting["location"]
        if mode is None:
            needs.append({"kind": "modalidade", "detail": (
                "A página não informa a modalidade (remoto, híbrido, presencial). Confira na vaga, registre com "
                "update_application (work_mode e location) e chame evaluate_salary com o application_id.")})
            return
        if posting.get("work_mode_inferred"):
            reasons.append(f"Modalidade {mode} inferida do texto da vaga (a página não publica); confira na vaga e, "
                           "se estiver errada, corrija com update_application (work_mode).")
        if mode == "remoto":
            reasons.append("Vaga remota.")
            return
        # Só a cidade (1ª parte): "Campinas, São Paulo, Brasil" não é a cidade de São Paulo.
        city = re.sub(r"^greater\s+|\s+area$", "", normalize_text(re.split(r",|\s+-\s+", location or "")[0]))
        state = state_of(location)
        if any(group.accepts(city, state) for group in criteria.places):
            reasons.append(f"Vaga {_MODE_LABELS[mode]} em local aceito ({location}).")
            return None
        if criteria.accepted_states and state and state not in criteria.accepted_states:
            return (f"Vaga {_MODE_LABELS[mode]} em {location} ({state}), fora dos estados aceitos para híbrido e "
                    f"presencial ({', '.join(criteria.accepted_states)}).")
        needs.append({"kind": "local", "detail": (
            f"Vaga {_MODE_LABELS[mode]} em {location or 'local não informado'}, fora dos locais aceitos. Julgue se o "
            "deslocamento é viável; se não for, descarte com update_application.")})

    def _salary(self, app: dict[str, Any], posting: dict[str, Any], needs: list[dict[str, Any]]) -> dict | None:
        role_key, seniority = posting["role_key"], posting["seniority"]
        published = posting.get("salary")
        currency = published["currency"] if published and published.get("currency") in CURRENCIES else "BRL"
        if not posting["role_certain"]:
            return None
        if seniority is None:
            needs.append({"kind": "senioridade", "detail": (
                "Senioridade não identificada pelo título. Defina pela descrição (anos de experiência, "
                "responsabilidades)" + (", registre a faixa publicada com save_salary_estimate (source 'vaga')"
                                        if published else "") +
                " e chame evaluate_salary com o application_id.")})
            return None
        if published:
            self._save_published(app, posting, currency, published, needs)
        if posting["work_mode"] is None:
            return None
        try:
            result = self.salaries.evaluate_salary(role_key, seniority, currency, posting["contract"],
                                                   company=posting["company"] or None, application_id=app["id"])
        except VagasError as exc:
            needs.append({"kind": "salario", "detail": f"Avaliação salarial não feita: {exc}"})
            return None
        if result["decision"] == "pesquisar" or result["needs_research"]:
            scope = "da empresa e de mercado" if result["decision"] == "pesquisar" else "da empresa"
            needs.append({"kind": "pesquisa_salarial", "queries": result["research_queries"], "detail": (
                f"Pesquise salários {scope} ({role_key}, {seniority}, {currency}) com as consultas de queries, "
                "na ordem (cargo e empresa primeiro, mercado por último). Registre com save_salary_estimate: dado "
                "da empresa com company; nada encontrado na empresa também (points vazio, com company), para não "
                "repetir; dado de mercado sem company. Depois chame evaluate_salary de novo com o application_id.")})
        return result

    def _save_published(self, app, posting, currency, published, needs) -> None:
        if published.get("period") is None:
            needs.append({"kind": "salario", "detail": (
                f"Faixa publicada sem período ({published}); confira na vaga e registre com save_salary_estimate.")})
            return
        try:
            self.salaries.save_salary_estimate(
                posting["role_key"], posting["seniority"], currency, company=posting["company"] or None,
                application_id=app["id"], points=[{
                    "source": "vaga", "source_url": posting["url"], "contract": posting["contract"],
                    "period": published["period"], "min_value": published.get("min_value"),
                    "max_value": published.get("max_value")}])
        except VagasError as exc:
            needs.append({"kind": "salario", "detail": f"Faixa publicada não registrada: {exc}"})

    def _level_fit(self, criteria: TriageCriteria, seniority: str | None) -> dict[str, Any] | None:
        """Enquadramento: anos de experiência do currículo geral contra a faixa do nível da vaga. Nível sem faixa na
        tabela (estágio, ou um que a tabela editada não traz): job_years e within nulos, mas a lista de senioridades
        ainda decide (listed)."""
        table = {level.name: level for level in criteria.years_by_level}
        if seniority not in SENIORITIES:  # sem nível, ou texto livre antigo: nada a conferir
            return None
        try:
            years = experience_years(self.resumes.get_master_resume()["resume"],
                                     datetime.fromisoformat(self.repo.now()).date())
        except VagasError:
            years = None
        job = table.get(seniority)
        return {
            "your_years": years,
            "your_level": level_for_years(years, criteria.years_by_level) if years is not None else None,
            "job_level": seniority, "job_years": job.years() if job else None,
            "within": None if years is None or job is None else (
                job.min <= years and (job.max is None or years <= job.max)),
            "listed": not criteria.search_seniorities or seniority in criteria.search_seniorities,
        }

    @staticmethod
    def _level(criteria: TriageCriteria, level: dict[str, Any], reasons: list[str]) -> str | None:
        """Os níveis só embasam: a lista de senioridades decide; fora do enquadramento a vaga segue."""
        job = f"Vaga {level['job_level']}" + (f" ({level['job_years']} anos)" if level["job_years"] else "")
        if not level["listed"]:
            return (f"{job} fora das senioridades a que você se candidata "
                    f"({', '.join(criteria.search_seniorities)}, em criterios-triagem.md).")
        if level["job_years"] is None:
            reasons.append(f"{job} entre as senioridades a que você se candidata (nível sem faixa de anos na tabela).")
            return None
        if level["your_years"] is None:
            return None
        years = f"{level['your_years']:.1f}".replace(".", ",")
        you = f"Você: {years} anos de experiência ({level['your_level']})"
        if level["within"]:
            reasons.append(f"{job} dentro do seu enquadramento. {you}.")
        else:
            reasons.append(f"{job} fora do seu enquadramento, mas {level['job_level']} está entre as senioridades "
                           f"a que você se candidata. {you}.")
        return None

    @staticmethod
    def _result(decision, application, posting, match, salary, reasons, needs, level=None) -> dict[str, Any]:
        return {
            "decision": decision,
            "level": level,
            "application": application,
            "posting": {k: v for k, v in posting.items() if k != "description"} if posting else None,
            "match": match,
            "salary": salary,
            "reasons": reasons,
            "needs": needs,
        }
