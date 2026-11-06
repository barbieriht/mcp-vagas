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
from datetime import datetime, timezone
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
                       "pinpointhq.com", "personio.com", "factorialhr.com")
TRUSTED_DOMAINS = (*AGGREGATORS, *PATH_PLATFORMS, *SUBDOMAIN_PLATFORMS)
# Plataformas que o usuário pode aprovar por inteiro (autofill_platforms): uma aprovação vale para todas as empresas.
PLATFORMS = (*PATH_PLATFORMS, *SUBDOMAIN_PLATFORMS)

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
    r"|\bterms\s+and\s+conditions\b|\bprivacy\s+(policy|notice|statement)\b")
_NOT_CONSENT = re.compile(
    r"\b(marketing|newsletter|novidades|ofertas|promoc\w*|comunicac\w*|e\s?mails?|sms|whatsapp|parceir\w*|"
    r"terceir\w*|outr[ao]s\s+(processos|vagas|oportunidades)|banco\s+de\s+talentos|publicidade|receber|receive|"
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
    """"termos" para o aceite de termos de uso / privacidade; None para marketing, parceiros e declarações de fato."""
    words = _words(text)
    if not words or _NOT_CONSENT.search(words):
        return None
    if re.search(r"\bdeclaro\b", words) and not _DECLARATION_OF_READING.search(words):
        return None
    return "termos" if _CONSENT.search(words) else None


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
    return Origin(domain, f"{domain} (todas as empresas)", host, remember=True)


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
                 platforms: Callable[[], list[str]] = lambda: []):
        self.vault = vault
        self.resumes = resumes
        self.max_file_bytes = max_file_bytes
        self.approvals = approvals
        self.log_path = Path(log_path)
        self.open_sites = open_sites
        self.extra_domains = extra_domains
        self.platforms = platforms

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
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
        terms = [(str(f.get("id")), " ".join(str(f.get("text") or "").split())) for f in fields
                 if f.get("kind") == "checkbox" and classify_consent(f.get("text") or "")]
        uploads = [str(f.get("id")) for f in fields if f.get("kind") == "file" and _accepts_pdf(f.get("accept"))
                   and (classify_upload(f.get("text") or "") or (not f.get("text") and classify_upload(f.get("attrs") or "")))]
        candidates = self._resume_candidates(request.get("url", ""), company, sites, extras) if uploads else []
        chosen_id = request.get("resume_application_id")
        needs_choice = len(candidates) > 1 and chosen_id is None
        if chosen_id is not None:
            resume = next((c for c in candidates if c["application_id"] == chosen_id), None)
        else:
            resume = candidates[0] if len(candidates) == 1 else None
        warnings = []
        if resume and Path(resume["path"]).stat().st_size > self.max_file_bytes:
            warnings.append(f"Currículo {Path(resume['path']).name} grande demais para a extensão "
                            f"({Path(resume['path']).stat().st_size // 1000} KB); anexe à mão: {resume['path']}")
            resume, needs_choice = None, False
        if not wanted and not terms and not resume and not needs_choice:
            return {"status": "nothing", **({"warnings": warnings} if warnings else {})}
        documents = list(dict.fromkeys(ALLOWED_FIELDS[doc] for _, doc, _ in wanted))
        term_texts = list(dict.fromkeys(text for _, text in terms))
        scopes = ({"documentos"} if wanted else set()) | ({"termos"} if terms else set()) | (
            {"curriculo"} if resume or needs_choice else set())
        confirm = request.get("confirm")
        if origin.remember and self.approvals.covers(origin.key, scopes) and not needs_choice:
            mode = "aprovada"
        elif confirm == "always" and origin.remember and not needs_choice:
            self.approvals.add(origin.key, origin.label, scopes)
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
                **({"warnings": warnings} if warnings else {})}

    def _resume_candidates(self, url: str, origin: Origin, sites: dict[str, str],
                           extras: list[str]) -> list[dict[str, Any]]:
        """Candidaturas abertas com currículo cuja vaga é a da página; sem nenhuma, as da mesma empresa ou site
        (nunca nos agregadores, onde o endereço não identifica a empresa)."""
        page = canonical_url(url) or ""
        parts = urlsplit(url)
        gupy_job = re.search(r"/jobs/(\d+)", parts.path) if (parts.hostname or "").endswith("gupy.io") else None
        exact, same = [], []
        for app in self.resumes():
            if not Path(app["path"]).is_file():
                continue
            canon = app.get("url_canonical") or ""
            if canon and (canon == page or page.startswith(canon + "/")
                          or (gupy_job and re.search(rf"\.gupy\.io/jobs/{gupy_job.group(1)}$", canon))):
                exact.append(app)
            elif origin.remember:
                try:
                    if resolve_origin(app.get("url") or "", sites, extras).key == origin.key:
                        same.append(app)
                except VagasError:
                    pass
        return exact or same

    def _log(self, entry: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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

    def _rows(self, sql: str) -> list[sqlite3.Row]:
        if not self.db_path.exists():
            return []
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, OPEN_STATUSES).fetchall()
        finally:
            conn.close()

    def sites(self) -> dict[str, str]:
        """Site próprio de cada candidatura aberta -> empresa."""
        sites = {}
        for row in self._rows(f"SELECT company, url FROM applications WHERE status IN ({_marks()}) ORDER BY updated_at"):
            host = (urlsplit(row["url"] or "").hostname or "").lower()
            if host and not any(_matches(host, d) for d in TRUSTED_DOMAINS):
                sites[site(host)] = row["company"]
        return sites

    def with_resumes(self) -> list[dict[str, Any]]:
        """Candidaturas abertas com o último currículo personalizado, no caminho onde foi salvo."""
        rows = self._rows(f"""
            SELECT a.id AS application_id, a.company, a.role, a.url, a.url_canonical, r.pdf_path AS path
            FROM applications a
            JOIN resumes r ON r.id = (SELECT MAX(id) FROM resumes WHERE application_id = a.id)
            WHERE a.status IN ({_marks()})
            ORDER BY a.updated_at DESC, a.id DESC""")
        return [dict(row) for row in rows]


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
