"""Extensão do Chrome de ponta a ponta: Chromium (Playwright) com a extensão carregada e o host de native
messaging de verdade, apontando para um cofre temporário. Páginas https simuladas por rota."""

import importlib.util
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("instalar_desktop", REPO / "scripts" / "instalar_desktop.py")
_inst = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_inst)
extension_id = _inst.extension_id
EXTENSION = REPO / "extension"
HOST_NAME = "com.barbieriht.vagas"

FORM = """<!doctype html><html><head><meta charset="utf-8"></head><body><form>
<label for="cpf">CPF *</label><input id="cpf" placeholder="000.000.000-00">
<div><span>Número do RG</span><input name="documento2"></div>
<label>CPF oculto <input id="hidden" style="display:none"></label>
<label>CPF já preenchido <input id="filled" value="111"></label>
<label for="nome">Nome completo</label><input id="nome">
<label for="rgdata">Data de emissão do RG</label><input id="rgdata">
<label><input type="checkbox" id="termos"> Li e concordo com os <a href="#">Termos de Uso</a></label>
<label><input type="checkbox" id="news"> Quero receber novidades por e-mail</label>
<label><input type="checkbox" id="declaro"> Declaro que não possuo parentes na empresa</label>
<label><input type="checkbox" id="priv" style="opacity:0;position:absolute;width:1px;height:1px">
  <span>Aceito a Política de Privacidade</span></label>
<div role="checkbox" aria-checked="false" id="lgpd" tabindex="0"
  onclick="this.setAttribute('aria-checked', 'true')">Autorizo o tratamento dos meus dados (LGPD)</div>
<div><button type="button">Anexar currículo</button><input type="file" id="cv" accept=".pdf,.doc" style="display:none"></div>
<div><span>Carta de apresentação</span><input type="file" id="carta"></div>
</form>
<script>
window.events = [];
document.getElementById("cpf").addEventListener("input", (e) => window.events.push(e.target.value));
document.getElementById("termos").addEventListener("change", (e) => window.events.push(e.target.checked));
window.uploaded = [];
document.getElementById("cv").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  const head = new TextDecoder().decode(await file.slice(0, 5).arrayBuffer());
  window.uploaded.push([file.name, file.size, file.type, head]);
});
</script></body></html>"""


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    cache = (Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" if os.name == "nt"
             else Path.home() / ".cache/ms-playwright")
    return any(cache.glob("chromium-*"))


# No Windows o Chromium só acha hosts de native messaging pelo Registro (no Linux, pela pasta do perfil).
# As chaves de teste são do Chromium e do Chrome for Testing, nunca a do Google Chrome do usuário.
_WINDOWS_HOST_KEYS = (rf"Software\Chromium\NativeMessagingHosts\{HOST_NAME}",
                      rf"Software\Google\Chrome for Testing\NativeMessagingHosts\{HOST_NAME}")


def _register_host(manifest: Path) -> None:
    if os.name != "nt":
        return
    import winreg

    for key in _WINDOWS_HOST_KEYS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, str(manifest))


def _unregister_host() -> None:
    if os.name != "nt":
        return
    import winreg

    for key in _WINDOWS_HOST_KEYS:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


pytestmark = pytest.mark.skipif(not _chromium_available(), reason="Playwright com Chromium não instalado")


@pytest.fixture
def browser(tmp_path):
    from playwright.sync_api import sync_playwright

    script = tmp_path / "host.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(REPO / 'tests')!r})
        from test_sensitive import FakeBackend
        from vagas.autofill import Applications, Approvals, Autofill
        from vagas.autofill_host import serve
        from vagas.sensitive import Vault
        apps = Applications({str(tmp_path / 'vagas.db')!r})
        autofill = Autofill(Vault({str(tmp_path / 'cofre.json')!r}, FakeBackend()),
                            Approvals({str(tmp_path / 'aprovacoes.json')!r}), log_path={str(tmp_path / 'autofill.log')!r},
                            open_sites=apps.sites, extra_domains=lambda: [], resumes=apps.with_resumes)
        serve(sys.stdin.buffer, sys.stdout.buffer, autofill)
    """), encoding="utf-8")
    if os.name == "nt":
        wrapper = tmp_path / "host.bat"
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{script}"\r\n', encoding="utf-8")
    else:
        wrapper = tmp_path / "host.sh"
        wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {script}\n", encoding="utf-8")
        wrapper.chmod(0o755)

    sys.path.insert(0, str(REPO / "tests"))
    from test_sensitive import FakeBackend
    from vagas.sensitive import Vault

    vault = Vault(tmp_path / "cofre.json", FakeBackend())
    vault.set("cpf", "529.982.247-25")
    vault.set("rg", "12.345.678-9")
    pdfs = _applications_with_resumes(tmp_path)

    profile = tmp_path / "perfil-chromium"
    hosts = profile / "NativeMessagingHosts"
    hosts.mkdir(parents=True)
    ext_id = extension_id(json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))["key"])
    manifest = hosts / f"{HOST_NAME}.json"
    manifest.write_text(json.dumps({
        "name": HOST_NAME, "description": "teste", "path": str(wrapper), "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"]}), encoding="utf-8")
    _register_host(manifest)

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(profile), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"])
            context.route("https://**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=FORM))
            yield context, tmp_path, pdfs
            context.close()
    finally:
        _unregister_host()


def _applications_with_resumes(tmp_path):
    """Candidaturas abertas com currículo personalizado gerado de verdade (PDF na pasta de saída)."""
    from resume_fixture import fictitious_resume
    from vagas.db import connect
    from vagas.repo import Repo
    from vagas.resume_repo import ResumeStore

    conn = connect(tmp_path / "vagas.db")
    store = ResumeStore(conn, tmp_path / "curriculo.yaml")
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    pdfs = {}
    for company, role, url in (("Acme", "Data Scientist", "https://acme.gupy.io/jobs/1"),
                               ("Empresa", "Analista", "https://careers.empresa.com.br/vagas/1"),
                               ("Empresa", "Engenheiro", "https://careers.empresa.com.br/vagas/2")):
        app = Repo(conn).add_application(company=company, role=role, source="outro", url=url,
                                         status="a_aplicar")["application"]
        created = store.create_tailored_resume({"label": company, "sections": [{"section": "experience"}]},
                                               tmp_path / "out", application_id=app["id"])
        pdfs[role] = Path(created["path"])
    conn.close()
    return pdfs


def _open_and_confirm(context, url, choice, shown=None):
    page = context.new_page()
    with context.expect_page(timeout=15000) as popup:
        page.goto(url)
    confirm = popup.value
    confirm.wait_for_load_state()
    button = confirm.get_by_role("button", name=choice)
    button.wait_for()
    if shown is not None:
        shown.append(confirm.inner_text("body"))
    button.click()
    return page


def test_fills_visible_document_fields_after_confirmation_and_remembers_the_company(browser):
    context, tmp_path, pdfs = browser

    shown = []
    page = _open_and_confirm(context, "https://acme.gupy.io/candidates/jobs/1/apply", "Permitir sempre para acme",
                             shown)

    page.wait_for_function("document.getElementById('cpf').value !== ''", timeout=15000)
    assert "CPF e RG" in shown[0] and "Li e concordo com os Termos de Uso" in shown[0]
    assert "novidades" not in shown[0] and "parentes" not in shown[0]
    assert page.is_checked("#termos") and page.is_checked("#priv")
    assert page.get_attribute("#lgpd", "aria-checked") == "true"
    assert not page.is_checked("#news") and not page.is_checked("#declaro")
    assert page.input_value("#cpf") == "529.982.247-25"
    assert page.input_value("[name=documento2]") == "12.345.678-9"
    assert page.input_value("#hidden") == "" and page.input_value("#filled") == "111"
    assert page.input_value("#nome") == "" and page.input_value("#rgdata") == ""
    assert sorted(map(str, page.evaluate("window.events"))) == ["529.982.247-25", "True"]
    pdf = pdfs["Data Scientist"]
    assert pdf.name in shown[0]
    page.wait_for_function("window.uploaded.length > 0", timeout=15000)
    assert page.evaluate("window.uploaded") == [[pdf.name, pdf.stat().st_size, "application/pdf", "%PDF-"]]
    assert page.evaluate("document.getElementById('carta').files.length") == 0

    again = context.new_page()
    again.goto("https://acme.gupy.io/candidates/jobs/2/apply")
    again.wait_for_function("document.getElementById('cpf').value !== '' && window.uploaded.length > 0", timeout=15000)
    assert len([p for p in context.pages if p.url.startswith("chrome-extension://")]) == 0
    log = (tmp_path / "autofill.log").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in log.splitlines()]
    assert "52998224725" not in log and "529.982" not in log
    assert [(e["host"], e["mode"]) for e in entries] == [("acme.gupy.io", "always"), ("acme.gupy.io", "aprovada")]
    assert entries[0]["resume"]["name"] == pdf.name


def test_with_several_applications_the_window_asks_which_resume(browser):
    context, _, pdfs = browser
    page = context.new_page()
    with context.expect_page(timeout=15000) as popup:
        page.goto("https://careers.empresa.com.br/candidatura")
    confirm = popup.value
    once = confirm.get_by_role("button", name="Só desta vez")
    once.wait_for()

    disabled_before = once.is_disabled()
    confirm.get_by_text(pdfs["Engenheiro"].name).click()
    once.click()

    page.wait_for_function("window.uploaded.length > 0", timeout=15000)
    assert disabled_before
    assert page.evaluate("window.uploaded")[0][0] == pdfs["Engenheiro"].name


def test_declining_leaves_the_fields_empty(browser):
    context, _, _ = browser

    page = _open_and_confirm(context, "https://www.linkedin.com/jobs/view/4012345678/", "Não preencher")

    page.wait_for_timeout(1500)
    assert page.input_value("#cpf") == "" and not page.is_checked("#termos")


def test_untrusted_sites_are_never_filled_nor_asked(browser):
    context, tmp_path, _ = browser
    page = context.new_page()

    page.goto("https://golpe.example.com/form")
    page.wait_for_timeout(2500)

    assert page.input_value("#cpf") == "" and not page.is_checked("#termos")
    assert page.evaluate("window.uploaded") == []
    assert not [p for p in context.pages if p.url.startswith("chrome-extension://")]
    assert not (tmp_path / "autofill.log").exists()
