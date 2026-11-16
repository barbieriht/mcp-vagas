"""Preenchimento de documentos do cofre (CPF, RG...) pela extensão do Chrome, sem passar pelo modelo.

A extensão (pasta `extension/`) acha os campos na página e pergunta ao host de native messaging
(`vagas.autofill_host`), que decide aqui:
- a página precisa ser https, num site de vagas confiável: agregadores (LinkedIn, Indeed...),
  plataformas de recrutamento, domínios extras do config (`autofill_domains`) ou o site de uma
  candidatura aberta;
- a primeira vez de cada empresa pede confirmação numa janela da extensão; "sempre" fica guardado
  em `autofill_aprovacoes.json`. Nos agregadores não há empresa confiável na URL: a confirmação vale
  só para a vaga;
- caixas de aceite de termos de uso e política de privacidade (nunca marketing, parceiros ou
  declarações de fato) são marcadas com a mesma regra; a confirmação mostra o texto de cada termo;
- o campo de arquivo do currículo recebe o PDF personalizado da candidatura daquela página, lido de onde
  create_tailored_resume o salvou (resumes.pdf_path); com mais de uma candidatura possível, a
  confirmação pede para escolher;
- cada preenchimento vai para `autofill.log`, sem os valores (com o texto dos termos aceitos e o
  currículo enviado).

Aprovações pelo terminal:
    python -m vagas.autofill list | revoke <chave> | revoke --all
"""

import argparse
import base64
import json
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from vagas.db import default_db_path
from vagas.normalize import canonical_url, normalize_text
from vagas.repo import VagasError
from vagas.sensitive import ALLOWED_FIELDS, OPEN_STATUSES, Vault, site

# Agregadores: várias empresas no mesmo endereço; a chave é a vaga.
AGGREGATORS = {"linkedin.com": "LinkedIn", "indeed.com": "Indeed", "glassdoor.com": "Glassdoor",
               "glassdoor.com.br": "Glassdoor", "catho.com.br": "Catho", "infojobs.com.br": "InfoJobs",
               "vagas.com.br": "Vagas.com"}
# Plataformas com a empresa no primeiro trecho do caminho (jobs.lever.co/empresa).
PATH_PLATFORMS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com", "kenoby.com",
                  "quickin.io", "jobvite.com")
# Plataformas com a empresa no subdomínio (empresa.gupy.io).
SUBDOMAIN_PLATFORMS = ("gupy.io", "myworkdayjobs.com", "inhire.app", "recrut.ai", "solides.com.br", "abler.com.br",
                       "recruitee.com", "teamtailor.com", "breezy.hr", "bamboohr.com", "icims.com", "taleo.net",
                       "pinpointhq.com", "personio.com", "factorialhr.com", "factorialhr.com.br", "csod.com")
TRUSTED_DOMAINS = (*AGGREGATORS, *PATH_PLATFORMS, *SUBDOMAIN_PLATFORMS)
# Plataformas que o usuário pode aprovar por inteiro (autofill_platforms): uma aprovação vale para todas as empresas.
PLATFORMS = (*PATH_PLATFORMS, *SUBDOMAIN_PLATFORMS)
# Aprovadas por inteiro mesmo sem configuração: ATS multiempresa conferidos (vagas reais na base ou formato público
# de uma página por empresa num domínio comum). autofill_platforms acrescenta outras e tira estas com "-dominio".
# Sólides fica fora: não há um formato confirmado de candidatura multiempresa. Sites white-label (Oracle Recruiting
# em domínio da empresa) não têm domínio comum: a aprovação continua por site.
DEFAULT_PLATFORMS = ("gupy.io", "inhire.app", "csod.com", "factorialhr.com.br", "myworkdayjobs.com", "greenhouse.io",
                     "lever.co", "smartrecruiters.com", "recruitee.com")
ALL_SCOPES = frozenset({"documentos", "termos", "banco_talentos", "curriculo"})


def effective_platforms(configured: str | list[str] | None) -> list[str]:
    """As padrão mais as de autofill_platforms; "-dominio" tira uma padrão."""
    items = configured if isinstance(configured, list) else re.split(r"[,;\s]+", (configured or "").strip().lower())
    removed = {i[1:] for i in items if i.startswith("-")}
    added = [i for i in items if i and not i.startswith("-")]
    return [d for d in dict.fromkeys((*DEFAULT_PLATFORMS, *added)) if d not in removed]

_JOB_PARAMS = ("currentJobId", "jk", "vjk", "jl", "jobListingId", "jobId", "id")

# Ordem importa: o órgão emissor antes do RG.
_PATTERNS: tuple[tuple[str, str], ...] = (
    ("rg_orgao_emissor", r"\borga?o?\s+(emissor|expedidor)\b|\borgao\b.*\b(rg|identidade)\b"),
    ("nome_mae", r"\bnome\s+(da\s+)?mae\b|\bmother\s*s?\s+(full\s+)?name\b|\bfiliacao\s+mae\b"),
    ("titulo_eleitor", r"\btitulo\s+(de\s+)?eleitor|\btitulo\s+eleitoral\b|\bvoter\b"),
    ("ctps", r"\bctps\b|\bcarteira\s+(de\s+)?trabalho\b"),
    ("cnh", r"\bcnh\b|\bcarteira\s+(nacional\s+)?(de\s+)?habilitacao\b|\bcarteira\s+de\s+motorista\b"
            r"|\bdriver\s*s?\s+licen[cs]e\b"),
    ("passaporte", r"\bpassaporte\b|\bpassport\b"),
    ("pis", r"\bpis\b|\bpasep\b|\bnis\b|\bnit\b"),
    ("cpf", r"\bcpf\b"),
    ("rg", r"\brg\b|\bregistro\s+geral\b|\b(carteira|cedula|numero|n)\s+(de\s+|da\s+)?identidade\b|^identidade$"),
)
_EXCLUDE = re.compile(r"\b(data|validade|vencimento|emissao|expedicao|categoria|possui|tem|foto|imagem|anexo|anexar|"
                      r"arquivo|upload|frente|verso|uf|estado|serie|zona|secao|genero|pai|digito|tipo|expiry|"
                      r"expiration|issue|date|country|pais)\b")


_CONSENT = re.compile(
    r"\btermos?\b.{0,30}\b(uso|servicos?|condicoes)\b|\bcondicoes\s+(gerais\s+)?(de\s+)?uso\b"
    r"|\b(politica|aviso|declaracao)\s+de\s+privacidade\b|\blgpd\b|\bprotecao\s+de\s+dados\b"
    r"|\btratamento\s+(dos\s+|de\s+)?(meus\s+)?dados\b|\bterms\s+(of\s+)?(use|service)\b"
    r"|\bterms\s+and\s+conditions\b|\bprivacy\s+(policy|notice|statement)\b"
    r"|\btermos?\s+de\s+consentimento\b|\bconsentimento\s+(livre|expresso|para\s+(o\s+)?tratamento)\b"
    r"|\bconsent\s+form\b"
    r"|\b(dados\s+pessoais|personal\s+data)\b.{0,80}\b(tratad\w*|tratamento|process\w*)\b"
    r"|\b(tratamento|tratar|processing|process)\b.{0,40}\b(dados\s+pessoais|personal\s+data)\b")
# Banco de talentos: marcado só quando o perfil diz "sim" em "Incluir em bancos de talentos".
_TALENT_POOL = re.compile(
    r"\bbanco\s+de\s+talentos\b|\btalent\s+(pool|community|network)\b"
    r"|\boutr[ao]s\s+(processos|vagas|oportunidades)\b|\bfutur[ao]s\s+(processos|vagas|oportunidades)\b")
_NOT_CONSENT = re.compile(
    r"\b(marketing|newsletter|novidades|ofertas|promoc\w*|comunicac\w*|e\s?mails?|sms|whatsapp|parceir\w*|"
    r"terceir\w*|publicidade|receber|receive|"
    r"partners?|third\s+part\w*)\b")
_UPLOAD = re.compile(r"\bcurriculo\b|\bcurriculum\b|\bcv\b|\bresume\b")
_NOT_RESUME = re.compile(r"\b(carta|cover|foto|photo|imagem|picture|portfolio|portifolio|documento|document|"
                        r"certificado|certificate|diploma|comprovante|historico|transcript)\b")
MAX_FILE_BYTES = 700_000  # mensagens do host para a extensão têm até 1 MB, e o PDF vai em base64
_DECLARATION_OF_READING = re.compile(r"\bdeclaro\s+(que\s+)?(li|ter\s+lido|estar\s+ciente|estou\s+ciente|"
                                     r"concordo|aceito)\b")


def _words(text: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")  # cpfCandidato
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalize_text(text)).split())


def classify(text: str) -> str | None:
    """Campo do cofre pedido por um rótulo de formulário, ou None (dados que não são o documento)."""
    words = _words(text)
    if not words or _EXCLUDE.search(words):
        return None
    return next((field for field, pattern in _PATTERNS if re.search(pattern, words)), None)


def classify_consent(text: str) -> str | None:
    """"termos" para o aceite de termos de uso, privacidade e consentimento; "banco_talentos" para a inclusão em
    banco de talentos (mesmo junto de termos); None para marketing, parceiros e declarações de fato."""
    words = _words(text)
    if not words or _NOT_CONSENT.search(words):
        return None
    if re.search(r"\bdeclaro\b", words) and not _DECLARATION_OF_READING.search(words):
        return None
    if _TALENT_POOL.search(words):
        return "banco_talentos"
    return "termos" if _CONSENT.search(words) else None


def classify_checkbox(text: str) -> str | None:
    """Caixa de marcar: "termos", "banco_talentos", "marketing" (comunicações, ofertas, parceiros), "declaracao"
    (declaração de fato, "Declaro que...") ou None (outra pergunta)."""
    words = _words(text)
    if not words:
        return None
    if re.search(r"\bdeclaro\b", words) and not _DECLARATION_OF_READING.search(words):
        return "declaracao"
    if _NOT_CONSENT.search(words):
        return "marketing"
    return classify_consent(text)


def classify_upload(text: str) -> str | None:
    """"curriculo" para o campo de arquivo do currículo; None para carta, foto, portfólio, documentos e afins."""
    words = _words(text)
    if not words or _NOT_RESUME.search(words):
        return None
    return "curriculo" if _UPLOAD.search(words) else None


def _accepts_pdf(accept: str | None) -> bool:
    kinds = {k.strip().lower() for k in (accept or "").split(",") if k.strip()}
    return not kinds or bool(kinds & {".pdf", "application/pdf", "*/*", "application/*"})


def classify_field(field: dict[str, Any]) -> str | None:
    """Rótulo visível primeiro; atributos (name, id, placeholder) só quando o rótulo não diz nada."""
    label = field.get("text") or ""
    found = classify(label)
    if found or (label and _EXCLUDE.search(_words(label))):
        return found
    return classify(field.get("attrs") or "")


def format_value(field: str, value: str, hint: dict[str, Any]) -> str:
    """Valor no formato da máscara do campo: CPF e PIS com pontuação se o campo pedir; nada maior que o limite."""
    placeholder = str(hint.get("placeholder") or "")
    try:
        maxlength = int(hint.get("maxlength") or 0)
    except (TypeError, ValueError):
        maxlength = 0
    digits = re.sub(r"\D", "", value)
    if field == "cpf" and len(digits) == 11:
        if "." in placeholder or "-" in placeholder or maxlength >= 14:
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
        return digits
    if field == "pis" and len(digits) == 11:
        if "." in placeholder or maxlength >= 14:
            return f"{digits[:3]}.{digits[3:8]}.{digits[8:10]}-{digits[10]}"
        return digits
    if 0 < maxlength < len(value):
        return re.sub(r"[^0-9A-Za-z]", "", value)[:maxlength]
    return value


@dataclass(frozen=True)
class Origin:
    key: str  # o que uma aprovação permanente cobre
    label: str  # nome mostrado na confirmação
    host: str
    remember: bool  # False nos agregadores: a confirmação vale só para a vaga
    platform: bool = False  # chave da plataforma inteira: "Permitir sempre" vale para todas as empresas dela


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _job_id(url_parts) -> str:
    query = parse_qs(url_parts.query)
    for name in _JOB_PARAMS:
        if query.get(name) and query[name][0].strip():
            return query[name][0].strip()
    if found := re.search(r"/(\d{4,})(/|$)", url_parts.path):
        return found.group(1)
    return url_parts.path.rstrip("/") or "/"


def resolve_origin(url: str, open_sites: dict[str, str], extra_domains: list[str],
                   platforms: list[str] | tuple[str, ...] = ()) -> Origin:
    """Empresa (ou vaga) dona do formulário; VagasError se a página não for https num site de vagas confiável.
    Numa plataforma de `platforms` (autofill_platforms), a chave é a plataforma: a aprovação vale para todas
    as empresas dela."""
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise VagasError("A página precisa ser https.")
    for domain, name in AGGREGATORS.items():
        if _matches(host, domain):
            return Origin(f"{domain}/vaga/{_job_id(parts)}", name, host, remember=False)
    for domain in PATH_PLATFORMS:
        if _matches(host, domain) and domain in platforms:
            return _whole_platform(domain, host)
        if _matches(host, domain):
            segments = [s for s in parts.path.split("/") if s]
            company = parse_qs(parts.query).get("for", [""])[0] if segments[:1] == ["embed"] else ""
            company = company or (segments[0] if segments else host)
            return Origin(f"{domain}/{company.lower()}", company, host, remember=True)
    for domain in SUBDOMAIN_PLATFORMS:
        if _matches(host, domain) and domain in platforms:
            return _whole_platform(domain, host)
        if _matches(host, domain):
            return Origin(host, host.split(".")[0], host, remember=True)
    for domain in extra_domains:
        domain = domain.strip().lower().lstrip(".")
        if domain and _matches(host, domain):
            return Origin(domain, domain, host, remember=True)
    if (own := site(host)) in open_sites:
        return Origin(own, open_sites[own], host, remember=True)
    raise VagasError(f"{host} não é um site de vagas confiável (agregadores, plataformas de recrutamento, "
                     "autofill_domains do config ou o site de uma candidatura aberta).")


def _whole_platform(domain: str, host: str) -> Origin:
    return Origin(domain, f"{domain} (todas as empresas)", host, remember=True, platform=True)


class Approvals:
    """Empresas com "Permitir sempre", num JSON ao lado do banco."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _load(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8") or "{}")

    def _save(self, data: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def _scopes(entry: dict[str, Any]) -> set[str]:
        scopes = set(entry.get("escopos") or ["documentos"])
        return scopes | {"termos"} if entry.get("termos") else scopes  # formato antigo: só documentos (+ termos)

    def covers(self, key: str, scopes: set[str] | frozenset[str] = frozenset()) -> bool:
        """A aprovação vale para o que a confirmação mencionou: documentos, termos e/ou currículo."""
        entry = self._load().get(key)
        return entry is not None and set(scopes) <= self._scopes(entry)

    def add(self, key: str, label: str, scopes: set[str] | frozenset[str] = frozenset({"documentos"})) -> None:
        data = self._load()
        merged = sorted(set(scopes) | (self._scopes(data[key]) if key in data else set()))
        data[key] = {"label": label, "approved_at": _now(), "escopos": merged}
        self._save(data)

    def remove(self, key: str) -> bool:
        data = self._load()
        if key not in data:
            return False
        del data[key]
        self._save(data)
        return True

    def clear(self) -> None:
        self._save({})

    def list(self) -> list[dict[str, str]]:
        return [{"key": key, **value} for key, value in sorted(self._load().items())]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Autofill:
    def __init__(self, vault: Vault, approvals: Approvals, log_path: Path | str,
                 open_sites: Callable[[], dict[str, str]], extra_domains: Callable[[], list[str]],
                 resumes: Callable[[], list[dict[str, Any]]] = lambda: [], max_file_bytes: int = MAX_FILE_BYTES,
                 platforms: Callable[[], list[str]] = lambda: [],
                 talent_pool: Callable[[], bool | None] = lambda: None,
                 consent_mode: Callable[[], str] = lambda: "extensao",
                 data_consent: Callable[[], bool | None] = lambda: None,
                 status_path: Path | str | None = None):
        self.vault = vault
        self.resumes = resumes
        self.max_file_bytes = max_file_bytes
        self.approvals = approvals
        self.log_path = Path(log_path)
        self.open_sites = open_sites
        self.extra_domains = extra_domains
        self.platforms = platforms
        self.talent_pool = talent_pool
        self.consent_mode = consent_mode  # "usuario": a extensão não marca caixa nenhuma
        self.data_consent = data_consent  # "não autorizo" no perfil: os termos nunca são marcados
        self.status = ExtensionStatus(status_path) if status_path is not None else None

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """Atende o pedido (ver _handle) e registra a atividade da extensão, sem valores (ExtensionStatus)."""
        response = self._handle(request)
        if self.status is not None:
            self.status.record(request, response)
        return response

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """{url, fields: [{id, kind?, text, attrs?, placeholder?, maxlength?, accept?}], confirm: None | "once" |
        "always", resume_application_id?}.

        kind "checkbox": caixa de aceite (só termos de uso e privacidade são marcados); kind "file": campo
        de arquivo (só o do currículo recebe o PDF personalizado); os demais são de texto (documentos do
        cofre). Respostas: refused (reason), nothing, confirm (origin, documents, terms, resumes; sem
        valores) ou filled (values por id do campo: texto, true ou {name, type, data}, label); warnings
        quando algo foi pulado."""
        try:
            sites, extras = self.open_sites(), self.extra_domains()
            origin = resolve_origin(request.get("url", ""), sites, extras, self.platforms())
            company = resolve_origin(request.get("url", ""), sites, extras)  # o currículo é sempre da empresa
        except VagasError as exc:
            return {"status": "refused", "reason": str(exc)}
        fields = request.get("fields") or []
        stored = set(self.vault.list())
        wanted = [(str(f.get("id")), doc, f) for f in fields
                  if f.get("kind") not in ("checkbox", "file") and (doc := classify_field(f)) and doc in stored]
        accepted = set() if self.consent_mode() == "usuario" else (
            {"termos"} if self.data_consent() is not False else set()) | (
            {"banco_talentos"} if self.talent_pool() is True else set())
        consents = [(str(f.get("id")), " ".join(str(f.get("text") or "").split()), kind) for f in fields
                    if f.get("kind") == "checkbox" and (kind := classify_consent(f.get("text") or "")) in accepted]
        terms = [(field_id, text) for field_id, text, _ in consents]
        uploads = [str(f.get("id")) for f in fields if f.get("kind") == "file" and _accepts_pdf(f.get("accept"))
                   and (classify_upload(f.get("text") or "") or (not f.get("text") and classify_upload(f.get("attrs") or "")))]
        candidates = self._resume_candidates(request.get("url", ""), company, sites, extras) if uploads else []
        chosen_id = request.get("resume_application_id")
        needs_choice = len(candidates) > 1 and chosen_id is None
        if chosen_id is not None:
            resume = next((c for c in candidates if c["application_id"] == chosen_id), None)
        else:
            resume = candidates[0] if len(candidates) == 1 else None
        warnings, resume_error = [], None
        if resume and Path(resume["path"]).stat().st_size > self.max_file_bytes:
            warnings.append(f"Currículo {Path(resume['path']).name} grande demais para a extensão "
                            f"({Path(resume['path']).stat().st_size // 1000} KB); anexe à mão: {resume['path']}")
            resume, needs_choice, resume_error = None, False, "grande_demais"
        if not wanted and not terms and not resume and not needs_choice:
            return {"status": "nothing", **({"warnings": warnings, "resume_error": resume_error} if warnings else {})}
        documents = list(dict.fromkeys(ALLOWED_FIELDS[doc] for _, doc, _ in wanted))
        term_texts = list(dict.fromkeys(text for _, text in terms))
        scopes = ({"documentos"} if wanted else set()) | {kind for _, _, kind in consents} | (
            {"curriculo"} if resume or needs_choice else set())
        confirm = request.get("confirm")
        if origin.remember and self.approvals.covers(origin.key, scopes) and not needs_choice:
            mode = "aprovada"
        elif confirm == "always" and origin.remember and not needs_choice:
            # Na plataforma inteira, a aprovação vale para tudo o que a extensão preenche em todas as empresas.
            self.approvals.add(origin.key, origin.label, ALL_SCOPES if origin.platform else scopes)
            mode = "always"
        elif confirm in ("once", "always") and not needs_choice:
            mode = "once"
        else:
            shown = candidates if needs_choice else [resume] if resume else []
            return {"status": "confirm", "documents": documents, "terms": term_texts,
                    "resumes": [_resume_summary(c) for c in shown],
                    "origin": {"key": origin.key, "label": origin.label, "host": origin.host,
                               "remember": origin.remember}}
        raw = {doc: self.vault.get(doc) for doc in dict.fromkeys(doc for _, doc, _ in wanted)}
        values: dict[str, Any] = {field_id: format_value(doc, raw[doc], field) for field_id, doc, field in wanted}
        values.update({field_id: True for field_id, _ in terms})
        entry: dict[str, Any] = {"at": _now(), "host": origin.host, "key": origin.key, "documents": documents,
                                 "mode": mode}
        if term_texts:
            entry["terms"] = term_texts
        if resume:
            path = Path(resume["path"])
            values[uploads[0]] = {"name": path.name, "type": "application/pdf",
                                  "data": base64.b64encode(path.read_bytes()).decode()}
            entry["resume"] = {"application_id": resume["application_id"], "name": path.name}
        self._log(entry)
        return {"status": "filled", "values": values, "label": origin.label,
                **({"warnings": warnings, "resume_error": resume_error} if warnings else {})}

    def _resume_candidates(self, url: str, origin: Origin, sites: dict[str, str],
                           extras: list[str]) -> list[dict[str, Any]]:
        """Candidaturas abertas com currículo cuja vaga (ou página do formulário, form_url) é a da página; sem
        nenhuma, as da mesma empresa ou site (nunca nos agregadores, onde o endereço não identifica a empresa)."""
        page = canonical_url(url) or ""
        parts = urlsplit(url)
        gupy_job = re.search(r"/jobs/(\d+)", parts.path) if (parts.hostname or "").endswith("gupy.io") else None
        exact, same = [], []
        for app in self.resumes():
            if not Path(app["path"]).is_file():
                continue
            urls = [app.get("url") or "", app.get("form_url") or ""]
            canons = [app.get("url_canonical") or "", canonical_url(urls[1]) or ""]
            if any(canon and (canon == page or page.startswith(canon + "/")
                              or (gupy_job and re.search(rf"\.gupy\.io/jobs/{gupy_job.group(1)}$", canon)))
                   for canon in canons):
                exact.append(app)
            elif origin.remember and origin.key in {_origin_key(url, sites, extras) for url in urls if url}:
                same.append(app)
        return exact or same

    def _log(self, entry: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _origin_key(url: str, sites: dict[str, str], extras: list[str], platforms: list[str] | tuple[str, ...] = ()) -> str | None:
    try:
        return resolve_origin(url, sites, extras, platforms).key
    except VagasError:
        return None


def _resume_summary(app: dict[str, Any]) -> dict[str, Any]:
    return {"application_id": app["application_id"], "label": f"{app['role']} — {app['company']}",
            "name": Path(app["path"]).name}


def default_approvals_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path or default_db_path()).parent / "autofill_aprovacoes.json"


def default_log_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path or default_db_path()).parent / "autofill.log"


class Applications:
    """Candidaturas abertas lidas do banco, só para leitura (sem migrar o banco)."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def _rows(self, sql: str, params: tuple[Any, ...] = OPEN_STATUSES) -> list[sqlite3.Row]:
        """{form_url} no SQL vira a coluna, ou NULL num banco que o servidor ainda não migrou (v16)."""
        if not self.db_path.exists():
            return []
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(applications)")}
            form_url = "a.form_url" if "form_url" in columns else "NULL"
            return conn.execute(sql.format(form_url=form_url), params).fetchall()
        finally:
            conn.close()

    def sites(self) -> dict[str, str]:
        """Site próprio de cada candidatura aberta -> empresa."""
        sites = {}
        rows = self._rows(f"SELECT a.company, a.url, {{form_url}} AS form_url FROM applications a "
                          f"WHERE a.status IN ({_marks()}) ORDER BY a.updated_at")
        for row in rows:
            for url in (row["url"], row["form_url"]):
                host = (urlsplit(url or "").hostname or "").lower()
                if host and not any(_matches(host, d) for d in TRUSTED_DOMAINS):
                    sites[site(host)] = row["company"]
        return sites

    def with_resumes(self) -> list[dict[str, Any]]:
        """Candidaturas abertas com o último currículo personalizado, no caminho onde foi salvo."""
        rows = self._rows(f"""
            SELECT a.id AS application_id, a.company, a.role, a.url, a.url_canonical, {{form_url}} AS form_url,
                   r.pdf_path AS path
            FROM applications a
            JOIN resumes r ON r.id = (SELECT MAX(id) FROM resumes WHERE application_id = a.id)
            WHERE a.status IN ({_marks()})
            ORDER BY a.updated_at DESC, a.id DESC""")
        return [dict(row) for row in rows]


    def recent(self, since: str) -> list[dict[str, Any]]:
        """Candidaturas mexidas desde `since` (ISO), de qualquer status, com o endereço da vaga e do formulário."""
        rows = self._rows("SELECT a.id, a.company, a.role, a.url, {form_url} AS form_url, a.status FROM applications a "
                          "WHERE a.updated_at >= ? ORDER BY a.updated_at DESC", (since,))
        return [dict(row) for row in rows]


# --- situação da extensão --------------------------------------------------------------------------

EXTENSION_VERSION = "1.4.0"  # a de extension/manifest.json; a extensão manda a dela em cada pedido
_RECENT = 20


def default_status_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path or default_db_path()).parent / "autofill_status.json"


def _version_tuple(version: str | None) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version or ""))


class ExtensionStatus:
    """Última atividade da extensão (autofill_status.json, ao lado do banco): quando falou com o host, a versão e as
    últimas consultas (site, resultado, quantos campos de cada tipo), nunca os valores. Cada pedido é um processo do
    host, então a gravação é atômica e a última vence; falha ao gravar nunca atrapalha o preenchimento."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def read(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.path)

    def record(self, request: dict[str, Any], response: dict[str, Any]) -> None:
        fields: dict[str, int] = {}
        for field in request.get("fields") or []:
            kind = {"checkbox": "termos", "file": "curriculo"}.get(field.get("kind"), "documentos")
            fields[kind] = fields.get(kind, 0) + 1
        entry: dict[str, Any] = {"at": _now(), "host": (urlsplit(request.get("url") or "").hostname or "").lower(),
                                 "status": response.get("status"), "fields": fields}
        parts = urlsplit(request.get("url") or "")
        if any(_matches(entry["host"], d) for d in AGGREGATORS) and (job := _job_id(parts)).isdigit():
            entry["job"] = job  # no agregador, a vaga é o que identifica a candidatura (jobId do LinkedIn)
        if fields.get("curriculo") or response.get("resume_error"):
            sent = any(isinstance(v, dict) for v in (response.get("values") or {}).values())
            entry["resume"] = (response.get("resume_error") or ("anexado" if sent else "a_confirmar"
                               if response.get("resumes") else "nao_encontrado"))
        if isinstance(request.get("probe"), dict):  # o que a extensão viu no modal (só contagens e sim/não)
            entry["probe"] = {str(k)[:30]: v for k, v in list(request["probe"].items())[:10]
                              if isinstance(v, bool | int) and not isinstance(v, str)}
        try:
            data = self.read() or {}
            recent = [e for e in data.get("recent") or [] if isinstance(e, dict)]
            same = ("host", "status", "fields", "resume", "job", "probe")
            if recent and all(recent[0].get(k) == entry.get(k) for k in same):
                entry["count"] = int(recent[0].get("count") or 1) + 1
                recent = recent[1:]
            self.write({"last_seen": entry["at"], "version": request.get("version") or data.get("version"),
                        "recent": [entry, *recent][:_RECENT]})
        except OSError:
            pass


def _when(text: str | None) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text or "")
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _log_entries(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and _when(entry.get("at")):
            entries.append(entry)
    return entries


def extension_report(status_path: Path | str, log_path: Path | str, db_path: Path | str,
                     now: datetime | None = None, days: int = 30,
                     platforms: list[str] | None = None) -> dict[str, Any]:
    """Situação da extensão para o Claude: known false sem rastro dela neste computador; senão last_seen,
    idle_hours, version, outdated, warnings, recent (últimas consultas) e applications (o que ela preencheu em
    cada candidatura mexida nos últimos `days` dias: currículo, documentos, termos)."""
    now = now or datetime.now(timezone.utc)
    status = ExtensionStatus(status_path).read()
    entries = _log_entries(Path(log_path))
    if not status and not entries:
        return {"known": False, "reason": "O MCP não vê nenhum rastro da extensão do Chrome neste computador: ela nunca "
                                          "falou com o host do mcp-vagas, ou o host usa outra pasta de dados."}
    seen = [m for m in (_when((status or {}).get("last_seen")), *(_when(e["at"]) for e in entries[-1:])) if m]
    last = max(seen)
    version = (status or {}).get("version")
    outdated = _version_tuple(version) < _version_tuple(EXTENSION_VERSION)
    idle = int((now - last).total_seconds() // 3600)
    recent = [e for e in (status or {}).get("recent") or [] if isinstance(e, dict)][:10]
    warnings = []
    if outdated:
        warnings.append(f"A extensão em uso é anterior à {EXTENSION_VERSION}: recarregue-a em chrome://extensions "
                        "(o instalador já copiou a versão nova).")
    if idle >= 72:
        warnings.append(f"Sem atividade da extensão há {idle // 24} dias: ela pode estar desligada ou fora deste "
                        "perfil do Chrome.")
    missing = sorted({e["host"] for e in recent if e.get("resume") == "nao_encontrado" and e.get("host")})
    if missing:
        warnings.append(f"Em {', '.join(missing)} a extensão viu o campo de currículo e não achou o PDF: gere o currículo "
                        "com o application_id e o form_url da aba.")
    return {"known": True, "last_seen": last.isoformat(), "idle_hours": idle, "version": version,
            "expected_version": EXTENSION_VERSION, "outdated": outdated, "warnings": warnings, "recent": recent,
            "applications": _filled_by_application(entries, db_path, now - timedelta(days=days),
                                                   effective_platforms("") if platforms is None else platforms)}


def _filled_by_application(entries: list[dict[str, Any]], db_path: Path | str, since: datetime,
                           platforms: list[str]) -> list[dict[str, Any]]:
    apps = Applications(db_path)
    sites = apps.sites()
    rows = apps.recent(since.isoformat())
    keys = {row["id"]: {k for url in (row["url"], row["form_url"]) if url
                        for k in (_origin_key(url, sites, []), _origin_key(url, sites, [], platforms)) if k}
            for row in rows}
    found: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if _when(entry["at"]) < since:
            continue
        chosen = (entry.get("resume") or {}).get("application_id")
        for row in rows:
            if row["id"] != chosen and entry.get("key") not in keys[row["id"]]:
                continue
            item = found.setdefault(row["id"], {"id": row["id"], "company": row["company"], "role": row["role"],
                                                "url": row["url"], "status": row["status"], "resume": None,
                                                "documents": set(), "terms": set(), "last_at": entry["at"]})
            item["documents"].update(entry.get("documents") or [])
            item["terms"].update(entry.get("terms") or [])
            if row["id"] == chosen:
                item["resume"] = entry["resume"].get("name")
            item["last_at"] = max(item["last_at"], entry["at"])
    result = []
    for item in sorted(found.values(), key=lambda i: i["last_at"], reverse=True)[:20]:
        result.append({**item, "documents": sorted(item["documents"]), "terms": len(item["terms"])})
    return result


def _marks() -> str:
    return ",".join("?" * len(OPEN_STATUSES))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m vagas.autofill", description="Empresas aprovadas para o "
                                     "preenchimento de documentos pela extensão do Chrome")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="mostra as empresas com 'Permitir sempre'")
    revoke = sub.add_parser("revoke", help="remove uma aprovação (ou todas, com --all)")
    revoke.add_argument("key", nargs="?", help="chave mostrada por list (ex.: acme.gupy.io)")
    revoke.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    approvals = Approvals(default_approvals_path())
    if args.command == "list":
        items = approvals.list()
        print("\n".join(f"{a['key']}  ({a['label']}, desde {a['approved_at']}: "
                        f"{', '.join(Approvals._scopes(a))})" for a in items) or "Nenhuma aprovação.")
    elif args.all:
        approvals.clear()
        print("Todas as aprovações foram removidas.")
    elif args.key:
        print(f"{args.key}: {'removida' if approvals.remove(args.key) else 'não estava aprovada'}.")
    else:
        parser.error("informe a chave ou --all")


if __name__ == "__main__":
    main()
