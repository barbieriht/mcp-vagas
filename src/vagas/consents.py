"""Caixas de consentimento dos formulários, decididas pela seção "Consentimentos" do perfil e por consent_mode.
Não depende de MCP.

- termos de uso, privacidade e LGPD: com consent_mode "claude", o Claude marca só com "autorizo" no perfil; com
  "extensao" (padrão), marca a extensão do Chrome; com "usuario", o próprio usuário. "não autorizo" nunca marca.
- banco de talentos: o "Incluir em bancos de talentos" do perfil; com "sim", marca quem o consent_mode diz.
- marketing, comunicações e parceiros: só com "sim" explícito em "Marketing e comunicações"; sem ele, desmarcada.
- declarações de fato ("Declaro que...") não são consentimento: respondem pelo perfil.
"""

from typing import Any

from vagas import diversity
from vagas.normalize import normalize_text

SECTION = "Consentimentos"
DATA = "Autorizar uso de dados para recrutamento (termos, privacidade, LGPD)"
MARKETING = "Marketing e comunicações"
TALENT_POOL = "Incluir em bancos de talentos"
DATA_QUESTION = diversity.Question(DATA, ("autorizo", "não autorizo"),
                                   (("não autorizo", ("nao",)), ("autorizo", ("autorizo", "sim", "aceito"))),
                                   (), closed=True, first_match=True, not_say=False)


def _norm(text: str) -> str:
    return " ".join(normalize_text(text or "").split())


def yes(value: str | None) -> bool | None:
    """"autorizo", "sim" -> True; "não autorizo", "não" -> False; vazio ou a preencher -> None."""
    text = _norm(value).rstrip(".!")
    if not text or text.startswith("<"):
        return None
    first = text.split(" ")[0]
    if first in ("nao", "n", "no"):
        return False
    if first in ("autorizo", "sim", "s", "yes", "aceito"):
        return True
    return None


def _field(profile: dict[str, Any], label: str) -> dict[str, Any] | None:
    key = _norm(label)
    return next((f for s in profile.get("sections") or [] for f in s.get("fields") or [] if _norm(f["label"]) == key),
                None)


def _pending(text: str) -> str:
    return f'consentimento: marcar caixa "{" ".join(text.split())[:160]}"'


def _missing(profile: dict[str, Any], label: str) -> dict[str, Any]:
    existing = _field(profile, label) is not None
    return {"blocked": True, "missing_field": label, "existing": existing,
            **({} if existing else {"section": SECTION}),
            "reason": f"O perfil não diz {label!r}: pergunte ao usuário uma vez e grave com add_profile_field "
                      "(mesmo label, value)."}


def _who_marks(text: str, mode: str, source: dict[str, Any]) -> dict[str, Any]:
    if mode == "claude":
        return {"answer": "marcar", "source": source}
    who = "a extensão do Chrome marca" if mode == "extensao" else "o usuário marca"
    return {"blocked": True, "handled_by": mode, "pending": _pending(text),
            "reason": f'Deixe desmarcada: {who} (consent_mode "{mode}"). Se continuar desmarcada quando terminar o '
                      "resto, registre o pending indicado."}


def resolve_checkbox(profile: dict[str, Any], text: str, mode: str) -> dict[str, Any]:
    """{answer: "marcar" | "desmarcar", source} ou {blocked: true, reason, handled_by?, pending?, missing_field?}."""
    from vagas.autofill import classify_checkbox

    kind = classify_checkbox(text)
    if kind == "termos":
        field = _field(profile, DATA)
        allowed = yes(field["value"]) if field else None
        if allowed is False:
            return {"blocked": True, "reason": "O perfil não autoriza o uso dos dados para recrutamento: não marque. "
                                               "Sem o aceite o formulário não deve ser enviado; registre no pending."}
        if mode == "claude" and allowed is None:
            return _missing(profile, DATA)
        return _who_marks(text, mode, {"kind": "perfil", "field": DATA})
    if kind == "banco_talentos":
        field = _field(profile, TALENT_POOL)
        wanted = yes(field["value"]) if field else None
        if wanted is None:
            return _missing(profile, TALENT_POOL)
        if wanted is False:
            return {"answer": "desmarcar", "source": {"kind": "perfil", "field": TALENT_POOL}}
        return _who_marks(text, mode, {"kind": "perfil", "field": TALENT_POOL})
    if kind == "marketing":
        field = _field(profile, MARKETING)
        if field and yes(field["value"]) is True:
            return {"answer": "marcar", "source": {"kind": "perfil", "field": MARKETING}}
        source = {"kind": "perfil", "field": MARKETING} if field and yes(field["value"]) is False else {"kind": "padrao"}
        return {"answer": "desmarcar", "source": source}
    reason = ("É uma declaração de fato, não um consentimento: responda pelo perfil (get_profile); o que não estiver "
              "lá é bloqueio." if kind == "declaracao" else
              "Caixa que não é de termos, banco de talentos nem marketing: trate como pergunta (checkbox false).")
    return {"blocked": True, "reason": reason}
