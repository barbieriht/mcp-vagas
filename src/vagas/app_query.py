"""Consulta estruturada das candidaturas e a mesma alteração aplicada a todas as que ela encontra. Não depende de MCP.

Os filtros se combinam (E) e nunca viram SQL do chamador: colunas e valores vêm de listas fechadas (models), e os
textos (local, cargo, empresa) são comparados em Python, sem acento nem maiúscula. A alteração em lote é simulada
antes (dry_run): a simulação devolve um confirm_token que amarra filtro, alteração e as candidaturas encontradas, e
a aplicação só vale com ele, dentro de 10 minutos e com o mesmo conjunto. Tudo numa transação, com a validação e o
evento de update_application em cada linha.
"""

import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vagas.models import (
    PROTECTED_STATUSES, QUERY_FIELDS, STATUSES, NeedKind, Seniority, Status, WorkMode,
)
from vagas.needs import kinds
from vagas.normalize import normalize_company, normalize_text
from vagas.places import state_code, state_of
from vagas.repo import Repo, VagasError, _application, _iso_instant, _require_choice

DEFAULT_FIELDS = ("id", "company", "role", "seniority", "work_mode", "location", "match_score", "status", "url")
SAMPLE_SIZE = 20
TOKEN_TTL = timedelta(minutes=10)
_SECRET = "bulk_update_secret"
_ORDER = {
    "-created_at": "a.created_at DESC, a.id DESC",
    "created_at": "a.created_at, a.id",
    "-match_score": "a.match_score IS NULL, a.match_score DESC, a.id",
    "match_score": "a.match_score IS NULL, a.match_score, a.id",
    "company": "a.company_norm, a.id",
    "id": "a.id",
    "-id": "a.id DESC",
}


class ApplicationFilter(BaseModel):
    """Filtros combinados (E); listas valem como "qualquer um destes". *_missing: true inclui as sem o campo (sozinho,
    só elas); false, só as com o campo."""

    model_config = ConfigDict(extra="forbid")
    status: Status | list[Status] | None = None
    seniority: list[Seniority] | None = None
    seniority_missing: bool | None = None
    work_mode: list[WorkMode] | None = None
    work_mode_missing: bool | None = None
    location_any: list[str] | None = None
    location_none: list[str] | None = None
    state_any: list[str] | None = None
    state_none: list[str] | None = None
    role_any: list[str] | None = None
    role_none: list[str] | None = None
    company_any: list[str] | None = None
    company_none: list[str] | None = None
    match_score_min: Annotated[int, Field(ge=0, le=100)] | None = None
    match_score_max: Annotated[int, Field(ge=0, le=100)] | None = None
    match_score_missing: bool | None = None
    needs_any: list[NeedKind] | None = None
    needs_none: list[NeedKind] | None = None
    search_id: int | None = None
    created_since: str | None = None
    created_until: str | None = None
    ids: list[int] | None = None

    def statuses(self) -> list[str]:
        return [self.status] if isinstance(self.status, str) else list(self.status or [])


def as_filter(value: Any) -> ApplicationFilter:
    """Filtro validado; VagasError dizendo o campo errado."""
    if isinstance(value, ApplicationFilter):
        return value
    try:
        return ApplicationFilter.model_validate(value or {})
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise VagasError(f"Filtro inválido ({problems}). Filtros aceitos: "
                         f"{', '.join(ApplicationFilter.model_fields)}.") from exc


# --- Consulta ---------------------------------------------------------------------------------------------


def _nullable(column: str, condition: str | None, missing: bool | None) -> str | None:
    """Condição sobre a coluna combinada com *_missing: true acrescenta as nulas; false exige o valor."""
    if condition and missing:
        return f"({condition} OR {column} IS NULL)"
    if condition:
        return condition
    if missing is True:
        return f"{column} IS NULL"
    if missing is False:
        return f"{column} IS NOT NULL"
    return None


def _in(column: str, values: list[str] | None, params: list[Any]) -> str | None:
    if not values:
        return None
    params.extend(values)
    return f"{column} IN ({', '.join('?' * len(values))})"


def _until(value: str) -> tuple[str, str]:
    """Data sem hora inclui o dia inteiro ("2026-11-05" = até 23:59:59); com hora, até o instante."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        next_day = datetime.fromisoformat(_iso_instant("created_until", value)) + timedelta(days=1)
        return "<", next_day.isoformat(timespec="seconds")
    return "<=", _iso_instant("created_until", value)


def _sql(flt: ApplicationFilter) -> tuple[str, list[Any]]:
    conditions: list[str | None] = []
    params: list[Any] = []
    conditions.append(_in("a.status", flt.statuses(), params))
    conditions.append(_nullable("a.seniority", _in("a.seniority", flt.seniority, params), flt.seniority_missing))
    conditions.append(_nullable("a.work_mode", _in("a.work_mode", flt.work_mode, params), flt.work_mode_missing))
    score = []
    for op, value in ((">=", flt.match_score_min), ("<=", flt.match_score_max)):
        if value is not None:
            score.append(f"a.match_score {op} ?")
            params.append(value)
    conditions.append(_nullable("a.match_score", " AND ".join(score) or None, flt.match_score_missing))
    if flt.search_id is not None:
        conditions.append("a.search_id = ?")
        params.append(flt.search_id)
    if flt.created_since:
        conditions.append("a.created_at >= ?")
        params.append(_iso_instant("created_since", flt.created_since))
    if flt.created_until:
        op, value = _until(flt.created_until)
        conditions.append(f"a.created_at {op} ?")
        params.append(value)
    if flt.ids is not None:
        conditions.append(f"a.id IN ({', '.join('?' * len(flt.ids))})" if flt.ids else "0")
        params.extend(flt.ids)
    where = " AND ".join(c for c in conditions if c)
    return (f"WHERE {where}" if where else ""), params


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _text_matchers(field: str, terms: list[str] | None) -> list[Any]:
    """Cada termo vira um teste sobre o texto já sem acento e em minúsculas: substring, ou expressão regular
    quando vem entre barras ("/\\bintern\\b/", sem diferenciar maiúsculas)."""
    matchers = []
    for term in terms or []:
        if len(term) > 2 and term.startswith("/") and term.endswith("/"):
            try:
                pattern = re.compile(_strip_accents(term[1:-1]), re.I)
            except re.error as exc:
                raise VagasError(f"'{field}' tem uma expressão regular inválida, {term!r}: {exc}. Escreva-a entre "
                                 "barras (ex.: /\\bintern\\b/) ou passe só o trecho a procurar.") from exc
            matchers.append(pattern.search)
        elif normalize_text(term):
            needle = normalize_text(term)
            matchers.append(lambda text, needle=needle: needle in text)
    return matchers


def _states(field: str, values: list[str] | None) -> set[str] | None:
    if values is None:
        return None
    codes = set()
    for value in values:
        code = state_code(value)
        if code is None:
            raise VagasError(f"'{field}' tem um estado desconhecido: {value!r}. Use a sigla (ex.: SP) ou o nome "
                             "do estado (ex.: São Paulo).")
        codes.add(code)
    return codes


def _companies(values: list[str] | None) -> list[Any]:
    patterns = [normalize_company(v) for v in values or [] if v.strip()]
    return [re.compile(rf"(?<![\w&]){re.escape(p)}(?![\w&])").search for p in patterns if p]


def _text_filter(flt: ApplicationFilter) -> Any:
    """Os filtros de texto, estado e needs, que o SQLite não compara sem acento: aplicados às linhas lidas."""
    location_any, location_none = (_text_matchers(f, getattr(flt, f)) for f in ("location_any", "location_none"))
    role_any, role_none = (_text_matchers(f, getattr(flt, f)) for f in ("role_any", "role_none"))
    state_any, state_none = _states("state_any", flt.state_any), _states("state_none", flt.state_none)
    company_any, company_none = _companies(flt.company_any), _companies(flt.company_none)
    needs_any, needs_none = set(flt.needs_any or ()), set(flt.needs_none or ())

    def passes(app: dict[str, Any]) -> bool:
        location, role = normalize_text(app.get("location") or ""), normalize_text(app["role"])
        state, company, needs = state_of(app.get("location")), app["company_norm"], set(kinds(app.get("needs")))
        return (
            (not flt.location_any or bool(app.get("location")) and any(m(location) for m in location_any))
            and not any(m(location) for m in location_none)
            and (state_any is None or state in state_any)
            and (state_none is None or state not in state_none)
            and (not flt.role_any or any(m(role) for m in role_any))
            and not any(m(role) for m in role_none)
            and (not flt.company_any or any(m(company) for m in company_any))
            and not any(m(company) for m in company_none)
            and (not needs_any or bool(needs & needs_any))
            and not needs & needs_none
        )

    return passes


def matching(repo: Repo, flt: ApplicationFilter, order_by: str = "id") -> list[dict[str, Any]]:
    """Todas as candidaturas (registro completo) que passam no filtro, na ordem pedida."""
    if order_by not in _ORDER:
        raise VagasError(f"'order_by' inválido: {order_by!r}. Valores aceitos: {', '.join(_ORDER)}.")
    where, params = _sql(flt)
    rows = repo.conn.execute(
        f"""
        SELECT a.*, (SELECT MAX(e.at) FROM events e WHERE e.application_id = a.id) AS last_event_at
        FROM applications a {where} ORDER BY {_ORDER[order_by]}
        """, params)
    passes = _text_filter(flt)
    return [app for app in map(_application, rows) if passes(app)]


def _row(app: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Linha enxuta: só os campos pedidos (id sempre), sem vazios; needs só com os tipos."""
    row = {}
    for field in ("id", *(f for f in fields if f != "id")):
        value = kinds(app.get("needs")) if field == "needs" else app.get(field)
        if value is not None and value != [] and value != {}:
            row[field] = value
    return row


def query(repo: Repo, filter: Any, fields: list[str] | None = None, limit: int = 500, offset: int = 0,
          order_by: str = "-created_at") -> dict[str, Any]:
    flt = as_filter(filter)
    fields = tuple(dict.fromkeys(fields)) if fields else DEFAULT_FIELDS
    unknown = [f for f in fields if f not in QUERY_FIELDS]
    if unknown:
        raise VagasError(f"'fields' inválido: {', '.join(map(repr, unknown))}. Valores aceitos: "
                         f"{', '.join(QUERY_FIELDS)} (a descrição da vaga fica em get_history).")
    if limit < 1 or offset < 0:
        raise VagasError("'limit' deve ser pelo menos 1 e 'offset' não pode ser negativo.")
    found = matching(repo, flt, order_by)
    page = {"count": len(found), "rows": [_row(app, fields) for app in found[offset:offset + limit]]}
    if offset + limit < len(found):
        page["next_offset"] = offset + limit
    return page


# --- Alteração em lote ------------------------------------------------------------------------------------


def _secret(repo: Repo) -> bytes:
    secret = repo.get_state(_SECRET)
    if secret is None:
        secret = secrets.token_hex(16)
        repo.set_state(_SECRET, secret)
    return secret.encode()


def _signatures(repo: Repo, issued: int, flt: ApplicationFilter, changes: dict[str, Any],
                ids: list[int]) -> tuple[str, str]:
    """(pedido, pedido + conjunto): a primeira diz se o token é desta alteração; a segunda, se as candidaturas
    encontradas são as mesmas da simulação."""
    secret = _secret(repo)
    request = json.dumps({"issued": issued, "filter": flt.model_dump(exclude_none=True, mode="json"),
                          "changes": changes}, sort_keys=True, ensure_ascii=False)
    sign = lambda text: hmac.new(secret, text.encode(), hashlib.sha256).hexdigest()[:16]  # noqa: E731
    return sign(request), sign(f"{request}|{json.dumps(sorted(ids))}")


def _check_token(repo: Repo, token: str | None, flt: ApplicationFilter, changes: dict[str, Any],
                 ids: list[int]) -> None:
    redo = "faça a simulação de novo (dry_run=true, com o mesmo filtro e a mesma alteração) e use o token novo."
    if not token:
        raise VagasError("Para aplicar, passe o confirm_token devolvido pela simulação (dry_run=true); " + redo)
    issued, _, digest = token.partition(".")
    if not issued.isdigit() or len(digest) != 32:
        raise VagasError(f"confirm_token inválido: {redo}")
    request, matched = _signatures(repo, int(issued), flt, changes, ids)
    if not hmac.compare_digest(digest[:16], request):
        raise VagasError(f"O confirm_token não é da simulação deste filtro e desta alteração: {redo}")
    if datetime.fromisoformat(repo.now()).timestamp() - int(issued) > TOKEN_TTL.total_seconds():
        raise VagasError(f"O confirm_token expirou (vale {int(TOKEN_TTL.total_seconds() // 60)} minutos): {redo}")
    if not hmac.compare_digest(digest[16:], matched):
        raise VagasError("O conjunto de candidaturas que o filtro encontra mudou desde a simulação (entrou, saiu ou "
                         f"mudou de status alguma vaga): {redo}")


def _write(repo: Repo, targets: list[dict[str, Any]], changes: dict[str, Any]) -> None:
    for app in targets:
        try:
            repo._update_row(app, **changes)
        except VagasError as exc:
            raise VagasError(f"Candidatura {app['id']}: {exc} Nada foi gravado; corrija o filtro ou a alteração e "
                             "faça a simulação de novo.") from exc


def bulk_update(
    repo: Repo,
    filter: Any = None,
    ids: list[int] | None = None,
    status: str | None = None,
    discard_reason: str | None = None,
    note: str | None = None,
    pending: str | None = None,
    dry_run: bool = True,
    confirm_token: str | None = None,
    max_affected: int = 300,
) -> dict[str, Any]:
    """Simulação (padrão): {would_affect, sample, skipped, confirm_token, expires_at}. Com dry_run=False e o token:
    {updated, skipped, ids}. skipped = [{id, reason}]: status protegido não citado no filtro, ou já no status pedido."""
    if (filter is None) == (ids is None):
        raise VagasError("Informe 'filter' (o mesmo de query_applications) ou 'ids' (lista explícita), um dos dois.")
    if ids is not None:
        if not ids:
            raise VagasError("'ids' está vazio: passe os ids das candidaturas a alterar.")
        flt = ApplicationFilter(ids=ids)
    else:
        flt = as_filter(filter)
        if not flt.model_dump(exclude_none=True):
            raise VagasError("Informe ao menos um filtro: a alteração em lote nunca vale para todas as candidaturas.")
    changes = {k: v for k, v in {"status": status, "discard_reason": discard_reason, "note": note,
                                 "pending": pending}.items() if v is not None}
    if not changes:
        raise VagasError("Nada a alterar: informe status, discard_reason, note ou pending.")
    _require_choice("status", status, STATUSES)
    if discard_reason is not None and status != "descartada":
        raise VagasError("'discard_reason' só pode ser informado com status 'descartada'.")
    if status == "descartada" and not (discard_reason or "").strip():
        raise VagasError("Status 'descartada' exige 'discard_reason', o motivo gravado em cada candidatura.")
    if max_affected < 1:
        raise VagasError("'max_affected' deve ser pelo menos 1.")

    matched = matching(repo, flt)
    named = set(flt.statuses())
    targets, skipped = [], []
    for app in matched:
        if app["status"] in PROTECTED_STATUSES and app["status"] not in named:
            skipped.append({"id": app["id"], "reason": f"status {app['status']!r} protegido: inclua-o em "
                                                       "filter.status para alterá-lo"})
        elif status is not None and app["status"] == status:
            skipped.append({"id": app["id"], "reason": f"já está com status {status!r}"})
        else:
            targets.append(app)
    if len(targets) > max_affected:
        raise VagasError(f"{len(targets)} candidaturas seriam alteradas, acima de max_affected={max_affected}. "
                         "Refine o filtro ou, se for isso mesmo, passe um max_affected maior.")
    matched_ids = [app["id"] for app in matched]

    if dry_run:
        if not targets:
            return {"would_affect": 0, "sample": [], "skipped": skipped}
        _secret(repo)  # gravado antes: a simulação desfaz a própria transação
        try:
            _write(repo, targets, changes)  # a mesma validação da aplicação, linha a linha
        finally:
            repo.conn.rollback()
        now = datetime.fromisoformat(repo.now())
        issued = int(now.timestamp())
        request, matched_sig = _signatures(repo, issued, flt, changes, matched_ids)
        return {"would_affect": len(targets), "sample": [_row(app, DEFAULT_FIELDS) for app in targets[:SAMPLE_SIZE]],
                "skipped": skipped, "confirm_token": f"{issued}.{request}{matched_sig}",
                "expires_at": (now + TOKEN_TTL).isoformat(timespec="seconds")}

    _check_token(repo, confirm_token, flt, changes, matched_ids)
    with repo.conn:
        _write(repo, targets, changes)
    return {"updated": len(targets), "skipped": skipped, "ids": [app["id"] for app in targets]}
