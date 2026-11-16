"""Caixas de consentimento pelo perfil: a vontade do usuário fica em "Consentimentos", e consent_mode diz quem marca
os termos (a extensão do Chrome, o Claude ou o próprio usuário)."""

import pytest
from mcp import Client

from test_sensitive import FakeBackend
from vagas import config, settings_form
from vagas.autofill import Approvals, Autofill, classify_checkbox
from vagas.consents import resolve_checkbox
from vagas.profile_fields import ProfileFiles
from vagas.sensitive import Vault
from vagas.server import build_server

pytestmark = pytest.mark.anyio

TERMS = "Li e concordo com a Política de Privacidade e o tratamento dos meus dados (LGPD)"
POOL = "Quero participar do banco de talentos para futuras oportunidades"
MARKETING = "Aceito receber comunicações e ofertas de parceiros por e-mail"
DECLARATION = "Declaro que não possuo parentes trabalhando na empresa"

PERFIL = """\
# Dados para formulários

## Contato e identificação
- Nome: Maria Teste

## Consentimentos
- Autorizar uso de dados para recrutamento (termos, privacidade, LGPD): {data}
- Marketing e comunicações: {marketing}
- Incluir em bancos de talentos: {pool}

## Outros campos de formulário
- CPF: informar manualmente
"""


def make_profile(tmp_path, data="autorizo", marketing="não", pool="sim", drop=()):
    text = PERFIL.format(data=data, marketing=marketing, pool=pool)
    text = "".join(line for line in text.splitlines(keepends=True) if not any(line.startswith(f"- {d}") for d in drop))
    (tmp_path / "perfil.md").write_text(text, encoding="utf-8")
    (tmp_path / "perfil.example.md").write_text(text, encoding="utf-8")
    return ProfileFiles(tmp_path).get_profile(vault_fields=[])


@pytest.mark.parametrize("text, kind", [
    (TERMS, "termos"), ("I agree to the Terms of Use", "termos"), (POOL, "banco_talentos"),
    (MARKETING, "marketing"), ("Quero receber a newsletter", "marketing"), (DECLARATION, "declaracao"),
    ("Tenho disponibilidade para viagens", None),
])
def test_checkboxes_are_classified(text, kind):
    assert classify_checkbox(text) == kind


def test_with_claude_mode_and_authorization_the_terms_are_checked(tmp_path):
    result = resolve_checkbox(make_profile(tmp_path), TERMS, "claude")

    assert result["answer"] == "marcar"
    assert result["source"]["field"].startswith("Autorizar uso de dados")


@pytest.mark.parametrize("mode, who", [("extensao", "extensao"), ("usuario", "usuario")])
def test_other_modes_leave_the_terms_to_the_extension_or_the_user_with_a_structured_pending(tmp_path, mode, who):
    result = resolve_checkbox(make_profile(tmp_path), TERMS, mode)

    assert result["blocked"] and result["handled_by"] == who
    assert result["pending"] == f'consentimento: marcar caixa "{TERMS}"'


def test_without_authorization_the_terms_are_never_checked(tmp_path):
    result = resolve_checkbox(make_profile(tmp_path, data="não autorizo"), TERMS, "claude")

    assert result["blocked"] and "answer" not in result and "não autoriza" in result["reason"]


def test_a_missing_authorization_is_asked_once_in_the_consent_section(tmp_path):
    profile = make_profile(tmp_path, drop=("Autorizar uso",))

    result = resolve_checkbox(profile, TERMS, "claude")

    assert result["missing_field"] == "Autorizar uso de dados para recrutamento (termos, privacidade, LGPD)"
    assert result["section"] == "Consentimentos" and result["existing"] is False


@pytest.mark.parametrize("marketing, answer", [("não", "desmarcar"), ("sim", "marcar")])
def test_marketing_follows_only_an_explicit_rule(tmp_path, marketing, answer):
    assert resolve_checkbox(make_profile(tmp_path, marketing=marketing), MARKETING, "claude")["answer"] == answer


def test_marketing_without_a_rule_stays_unchecked(tmp_path):
    result = resolve_checkbox(make_profile(tmp_path, drop=("Marketing",)), MARKETING, "claude")

    assert result["answer"] == "desmarcar" and result["source"]["kind"] == "padrao"


@pytest.mark.parametrize("pool, mode, expected", [
    ("sim", "claude", {"answer": "marcar"}), ("sim", "extensao", {"handled_by": "extensao"}),
    ("não", "claude", {"answer": "desmarcar"}), ("não", "extensao", {"answer": "desmarcar"}),
])
def test_talent_pool_follows_the_profile(tmp_path, pool, mode, expected):
    result = resolve_checkbox(make_profile(tmp_path, pool=pool), POOL, mode)

    assert {k: result.get(k) for k in expected} == expected


def test_declarations_of_fact_are_not_consents(tmp_path):
    result = resolve_checkbox(make_profile(tmp_path), DECLARATION, "claude")

    assert result["blocked"] and "declaração" in result["reason"] and "handled_by" not in result


def test_consent_mode_setting(db_path):
    assert config.resolve("consent_mode", db_path) == ("extensao", "default")
    config.write({"consent_mode": config.clean("consent_mode", "Usuário", db_path)}, db_path)
    assert config.resolve("consent_mode", db_path)[0] == "usuario"
    assert config.clean("consent_mode", "Extensão do Chrome", db_path) == "extensao"
    with pytest.raises(Exception, match="claude"):
        config.clean("consent_mode", "talvez", db_path)


async def test_the_tool_decides_checkboxes_by_the_consent_mode(db_path, tmp_path, monkeypatch):
    make_profile(tmp_path)
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(tmp_path))
    async with Client(build_server(db_path, vault=Vault(tmp_path / "cofre.json", FakeBackend()))) as client:
        default = (await client.call_tool("resolve_form_answer", {"question": TERMS, "checkbox": True}))
        await client.call_tool("set_config", {"key": "consent_mode", "value": "claude"})
        claude = (await client.call_tool("resolve_form_answer", {"question": TERMS, "checkbox": True}))

    assert default.structured_content["handled_by"] == "extensao"
    assert claude.structured_content["answer"] == "marcar"


# --- extensão do Chrome ----------------------------------------------------------------------------

def host(tmp_path, mode="extensao", data=True):
    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    return Autofill(vault, Approvals(tmp_path / "aprovacoes.json"), log_path=tmp_path / "autofill.log",
                    open_sites=lambda: {}, extra_domains=lambda: [], talent_pool=lambda: True,
                    consent_mode=lambda: mode, data_consent=lambda: data)


def ask(autofill):
    return autofill.handle({"url": "https://acme.gupy.io/jobs/1", "confirm": "once",
                            "fields": [{"id": "t", "kind": "checkbox", "text": TERMS},
                                       {"id": "p", "kind": "checkbox", "text": POOL}]})


@pytest.mark.parametrize("mode, data, checked", [
    ("extensao", True, {"t", "p"}), ("extensao", None, {"t", "p"}), ("claude", True, {"t", "p"}),
    ("usuario", True, set()), ("extensao", False, {"p"}),
])
def test_the_extension_marks_terms_only_when_the_mode_and_the_profile_allow(tmp_path, mode, data, checked):
    response = ask(host(tmp_path, mode, data))

    assert set(response.get("values") or {}) == checked


# --- painel ----------------------------------------------------------------------------------------

def test_the_panel_offers_the_consent_fields_and_the_mode(db_path, tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    examples = Path(__file__).resolve().parents[1] / "skill" / "candidaturas"
    shutil.copy(examples / "perfil.example.md", tmp_path / "perfil.example.md")
    (tmp_path / "perfil.md").write_text("## Contato e identificação\n- Nome: Maria\n\n"
                                        "## Outros campos de formulário\n- CPF: informar manualmente\n", encoding="utf-8")
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(tmp_path))

    data = settings_form.load(db_path)
    profile = {f["id"]: f for g in data["sections"]["profile"]["groups"] for f in g["fields"]}
    consent = profile["Consentimentos/Autorizar uso de dados para recrutamento (termos, privacidade, LGPD)"]
    mode = next(f for f in data["sections"]["config"]["fields"] if f["key"] == "consent_mode")

    assert consent["kind"] == "choice" and consent["missing"]
    assert [c["value"] for c in consent["choices"]] == ["", "autorizo", "não autorizo"]
    assert profile["Consentimentos/Marketing e comunicações"]["kind"] == "yesno"
    assert [c["value"] for c in mode["choices"]] == ["extensao", "claude", "usuario"]

    result = settings_form.save({"profile": {consent["id"]: "autorizo",
                                             "Consentimentos/Marketing e comunicações": "não"}}, db_path)

    assert result["saved"], result["errors"]
    assert ("## Consentimentos\n- Autorizar uso de dados para recrutamento (termos, privacidade, LGPD): autorizo\n"
            "- Marketing e comunicações: não\n\n## Outros campos de formulário") in (tmp_path / "perfil.md").read_text(encoding="utf-8")
