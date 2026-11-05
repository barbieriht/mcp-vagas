"""Preenchimento de documentos do cofre (CPF, RG...) pela extensão do Chrome, sem passar pelo modelo.

A extensão (pasta `extension/`) acha os campos na página e pergunta ao host de native messaging
(`vagas.autofill_host`), que decide aqui:
- a página precisa ser https, num site de vagas confiável: agregadores (LinkedIn, Indeed...),
  plataformas de recrutamento, domínios extras do config (`autofill_domains`) ou o site de uma
  candidatura aberta;
- a primeira vez de cada empresa pede confirmação numa janela da extensão; "sempre" fica guardado
  em `autofill_aprovacoes.json`. Nos agregadores não há empresa confiável na URL: a confirmação vale
  só para a vaga;
- cada preenchimento vai para `autofill.log`, sem os valores.

Aprovações pelo terminal:
    python -m vagas.autofill list | revoke <chave> | revoke --all
"""

import argparse
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
from vagas.normalize import normalize_text
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


def _words(text: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")  # cpfCandidato
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalize_text(text)).split())


def classify(text: str) -> str | None:
    """Campo do cofre pedido por um rótulo de formulário, ou None (dados que não são o documento)."""
    words = _words(text)
    if not words or _EXCLUDE.search(words):
        return None
    return next((field for field, pattern in _PATTERNS if re.search(pattern, words)), None)


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


def resolve_origin(url: str, open_sites: dict[str, str], extra_domains: list[str]) -> Origin:
    """Empresa (ou vaga) dona do formulário; VagasError se a página não for https num site de vagas confiável."""
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise VagasError("A página precisa ser https.")
    for domain, name in AGGREGATORS.items():
        if _matches(host, domain):
            return Origin(f"{domain}/vaga/{_job_id(parts)}", name, host, remember=False)
    for domain in PATH_PLATFORMS:
        if _matches(host, domain):
            segments = [s for s in parts.path.split("/") if s]
            company = parse_qs(parts.query).get("for", [""])[0] if segments[:1] == ["embed"] else ""
            company = company or (segments[0] if segments else host)
            return Origin(f"{domain}/{company.lower()}", company, host, remember=True)
    for domain in SUBDOMAIN_PLATFORMS:
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

    def has(self, key: str) -> bool:
        return key in self._load()

    def add(self, key: str, label: str) -> None:
        data = self._load()
        data[key] = {"label": label, "approved_at": _now()}
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
                 open_sites: Callable[[], dict[str, str]], extra_domains: Callable[[], list[str]]):
        self.vault = vault
        self.approvals = approvals
        self.log_path = Path(log_path)
        self.open_sites = open_sites
        self.extra_domains = extra_domains

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """{url, fields: [{id, text, attrs?, placeholder?, maxlength?}], confirm: None | "once" | "always"}.

        Respostas: refused (reason), nothing, confirm (origin, documents; sem valores) ou
        filled (values por id do campo, label)."""
        try:
            origin = resolve_origin(request.get("url", ""), self.open_sites(), self.extra_domains())
        except VagasError as exc:
            return {"status": "refused", "reason": str(exc)}
        stored = set(self.vault.list())
        wanted = [(str(f.get("id")), doc, f) for f in request.get("fields") or []
                  if (doc := classify_field(f)) and doc in stored]
        if not wanted:
            return {"status": "nothing"}
        documents = list(dict.fromkeys(ALLOWED_FIELDS[doc] for _, doc, _ in wanted))
        confirm = request.get("confirm")
        if origin.remember and self.approvals.has(origin.key):
            mode = "aprovada"
        elif confirm == "always" and origin.remember:
            self.approvals.add(origin.key, origin.label)
            mode = "always"
        elif confirm in ("once", "always"):
            mode = "once"
        else:
            return {"status": "confirm", "documents": documents,
                    "origin": {"key": origin.key, "label": origin.label, "host": origin.host,
                               "remember": origin.remember}}
        raw = {doc: self.vault.get(doc) for doc in dict.fromkeys(doc for _, doc, _ in wanted)}
        values = {field_id: format_value(doc, raw[doc], field) for field_id, doc, field in wanted}
        self._log({"at": _now(), "host": origin.host, "key": origin.key, "documents": documents, "mode": mode})
        return {"status": "filled", "values": values, "label": origin.label}

    def _log(self, entry: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def default_approvals_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path or default_db_path()).parent / "autofill_aprovacoes.json"


def default_log_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path or default_db_path()).parent / "autofill.log"


def open_application_sites(db_path: Path | str) -> dict[str, str]:
    """Site próprio de cada candidatura aberta -> empresa (só leitura; sem migrar o banco)."""
    path = Path(db_path)
    if not path.exists():
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(f"SELECT company, url FROM applications WHERE status IN ({','.join('?' * len(OPEN_STATUSES))})"
                            " ORDER BY updated_at", OPEN_STATUSES).fetchall()
    finally:
        conn.close()
    sites = {}
    for company, url in rows:
        host = (urlsplit(url or "").hostname or "").lower()
        if host and not any(_matches(host, d) for d in TRUSTED_DOMAINS):
            sites[site(host)] = company
    return sites


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
        print("\n".join(f"{a['key']}  ({a['label']}, desde {a['approved_at']})" for a in items) or "Nenhuma aprovação.")
    elif args.all:
        approvals.clear()
        print("Todas as aprovações foram removidas.")
    elif args.key:
        print(f"{args.key}: {'removida' if approvals.remove(args.key) else 'não estava aprovada'}.")
    else:
        parser.error("informe a chave ou --all")


if __name__ == "__main__":
    main()
