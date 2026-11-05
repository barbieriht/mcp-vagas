"""Extensão do Chrome de ponta a ponta: Chromium (Playwright) com a extensão carregada e o host de native
messaging de verdade, apontando para um cofre temporário. Páginas https simuladas por rota."""

import json
import sys
import textwrap
from pathlib import Path

import importlib.util

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("instalar_desktop", REPO / "scripts" / "instalar_desktop.py")
_inst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_inst)
extension_id = _inst.extension_id
EXTENSION = REPO / "extension"
HOST_NAME = "com.barbieriht.vagas"

FORM = """<!doctype html><html><body><form>
<label for="cpf">CPF *</label><input id="cpf" placeholder="000.000.000-00">
<div><span>Número do RG</span><input name="documento2"></div>
<label>CPF oculto <input id="hidden" style="display:none"></label>
<label>CPF já preenchido <input id="filled" value="111"></label>
<label for="nome">Nome completo</label><input id="nome">
<label for="rgdata">Data de emissão do RG</label><input id="rgdata">
</form>
<script>
window.events = [];
document.getElementById("cpf").addEventListener("input", (e) => window.events.push(e.target.value));
</script></body></html>"""


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return any((Path.home() / ".cache/ms-playwright").glob("chromium-*"))


pytestmark = pytest.mark.skipif(not _chromium_available(), reason="Playwright com Chromium não instalado")


@pytest.fixture
def browser(tmp_path):
    from playwright.sync_api import sync_playwright

    script = tmp_path / "host.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(REPO / 'tests')!r})
        from test_sensitive import FakeBackend
        from vagas.autofill import Approvals, Autofill
        from vagas.autofill_host import serve
        from vagas.sensitive import Vault
        autofill = Autofill(Vault({str(tmp_path / 'cofre.json')!r}, FakeBackend()),
                            Approvals({str(tmp_path / 'aprovacoes.json')!r}), log_path={str(tmp_path / 'autofill.log')!r},
                            open_sites=lambda: {{}}, extra_domains=lambda: [])
        serve(sys.stdin.buffer, sys.stdout.buffer, autofill)
    """), encoding="utf-8")
    wrapper = tmp_path / "host.sh"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {script}\n", encoding="utf-8")
    wrapper.chmod(0o755)

    sys.path.insert(0, str(REPO / "tests"))
    from test_sensitive import FakeBackend
    from vagas.sensitive import Vault

    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    vault.set("cpf", "529.982.247-25")
    vault.set("rg", "12.345.678-9")

    profile = tmp_path / "perfil-chromium"
    hosts = profile / "NativeMessagingHosts"
    hosts.mkdir(parents=True)
    ext_id = extension_id(json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))["key"])
    (hosts / f"{HOST_NAME}.json").write_text(json.dumps({
        "name": HOST_NAME, "description": "teste", "path": str(wrapper), "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"]}), encoding="utf-8")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"])
        context.route("https://**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=FORM))
        yield context, tmp_path
        context.close()


def _open_and_confirm(context, url, choice):
    page = context.new_page()
    with context.expect_page(timeout=15000) as popup:
        page.goto(url)
    confirm = popup.value
    confirm.wait_for_load_state()
    confirm.get_by_role("button", name=choice).click()
    return page


def test_fills_visible_document_fields_after_confirmation_and_remembers_the_company(browser):
    context, tmp_path = browser

    page = _open_and_confirm(context, "https://acme.gupy.io/candidates/jobs/1/apply", "Permitir sempre para acme")

    page.wait_for_function("document.getElementById('cpf').value !== ''", timeout=15000)
    assert page.input_value("#cpf") == "529.982.247-25"
    assert page.input_value("[name=documento2]") == "12.345.678-9"
    assert page.input_value("#hidden") == "" and page.input_value("#filled") == "111"
    assert page.input_value("#nome") == "" and page.input_value("#rgdata") == ""
    assert page.evaluate("window.events") == ["529.982.247-25"]

    again = context.new_page()
    again.goto("https://acme.gupy.io/candidates/jobs/2/apply")
    again.wait_for_function("document.getElementById('cpf').value !== ''", timeout=15000)
    assert len([p for p in context.pages if p.url.startswith("chrome-extension://")]) == 0
    log = (tmp_path / "autofill.log").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in log.splitlines()]
    assert "52998224725" not in log and "529.982" not in log
    assert [(e["host"], e["mode"]) for e in entries] == [("acme.gupy.io", "always"), ("acme.gupy.io", "aprovada")]


def test_declining_leaves_the_fields_empty(browser):
    context, _ = browser

    page = _open_and_confirm(context, "https://www.linkedin.com/jobs/view/4012345678/", "Não preencher")

    page.wait_for_timeout(1500)
    assert page.input_value("#cpf") == ""


def test_untrusted_sites_are_never_filled_nor_asked(browser):
    context, tmp_path = browser
    page = context.new_page()

    page.goto("https://golpe.example.com/form")
    page.wait_for_timeout(2500)

    assert page.input_value("#cpf") == ""
    assert not [p for p in context.pages if p.url.startswith("chrome-extension://")]
    assert not (tmp_path / "autofill.log").exists()
