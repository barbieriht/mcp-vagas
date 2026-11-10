"""Painel local de configuração: servidor HTTP real numa porta efêmera, só em 127.0.0.1, com token."""

import http.client
import json
import re
import threading

import pytest

from vagas import panel
from vagas.config import config_path, resolve


@pytest.fixture
def running(db_path):
    server = panel.make_server(db_path, token="t0k3n")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def request(server, method, path, body=None, headers=None, host=None, length=None):
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", host or f"127.0.0.1:{port}")
    for name, value in (headers or {}).items():
        conn.putheader(name, value)
    if data is not None:
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(length if length is not None else len(data)))
    conn.endheaders(data)
    response = conn.getresponse()
    return response.status, response.read().decode("utf-8")


TOKEN = {"X-Panel-Token": "t0k3n"}


def test_only_listens_on_localhost(running):
    assert running.server_address[0] == "127.0.0.1"


def test_page_needs_the_token_in_the_link(running):
    ok, page = request(running, "GET", "/?t=t0k3n")
    denied, _ = request(running, "GET", "/")

    assert ok == 200 and "Salvar tudo" in page and '<script src="/panel.js"' in page
    assert denied == 403


def test_page_loads_nothing_from_the_internet(running):
    _, page = request(running, "GET", "/?t=t0k3n")

    assert not re.search(r"(src|href)=[\"']?(https?:)?//", page)


def test_scripts_and_styles_are_served_without_the_token(running):
    script, js = request(running, "GET", "/panel.js")
    style, _ = request(running, "GET", "/panel.css")

    assert script == 200 and style == 200 and "/api/settings" in js


def test_api_needs_the_token(running):
    ok, body = request(running, "GET", "/api/settings", headers=TOKEN)
    denied, _ = request(running, "GET", "/api/settings", headers={"X-Panel-Token": "errado"})

    assert ok == 200 and "config" in json.loads(body)["sections"]
    assert denied == 403


def test_other_host_names_are_refused(running):
    # DNS rebinding: um site que aponta o próprio nome para 127.0.0.1 chega com outro Host.
    status, _ = request(running, "GET", "/api/settings", headers=TOKEN, host="ataque.example.com")

    assert status == 403


def test_saving_from_another_origin_is_refused(running, db_path, tmp_path):
    form = {"config": {"export_dir": str(tmp_path / "csv")}}

    status, _ = request(running, "POST", "/api/settings", form, {**TOKEN, "Origin": "https://ataque.example.com"})

    assert status == 403 and not config_path(db_path).exists()


def test_saving_from_the_panel_writes_the_config(running, db_path, tmp_path):
    port = running.server_address[1]
    form = {"config": {"export_dir": str(tmp_path / "csv")}}

    status, body = request(running, "POST", "/api/settings", form, {**TOKEN, "Origin": f"http://127.0.0.1:{port}"})

    assert status == 200 and json.loads(body)["saved"]
    assert resolve("export_dir", db_path) == (tmp_path / "csv", "config")


def test_invalid_fields_come_back_with_errors(running):
    status, body = request(running, "POST", "/api/settings", {"config": {"max_open_tabs": "99"}}, TOKEN)

    assert status == 200 and "config.max_open_tabs" in json.loads(body)["errors"]


@pytest.mark.parametrize("body, length, expected", [(b"{nao e json", None, 400), (b"{}", 2 * 1024 * 1024, 413)])
def test_broken_or_huge_bodies_are_refused(running, body, length, expected):
    # O tamanho anunciado basta: o painel recusa sem ler o corpo.
    status, _ = request(running, "POST", "/api/settings", body, TOKEN, length=length)

    assert status == expected


def test_a_second_start_reuses_the_open_panel(db_path):
    server = panel.make_server(db_path, token="abc")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        panel.remember(server, db_path)
        url = panel.running_url(db_path)
        assert url == f"http://127.0.0.1:{server.server_address[1]}/?t=abc"
    finally:
        server.shutdown()
        server.server_close()

    assert panel.running_url(db_path) is None  # painel fechado: o estado antigo não vale


def test_the_saved_state_is_private(db_path):
    import os
    import stat

    server = panel.make_server(db_path, token="abc")
    try:
        state = panel.remember(server, db_path)
    finally:
        server.server_close()

    if os.name != "nt":
        assert stat.S_IMODE(state.stat().st_mode) == 0o600


def _chromium():
    from test_extension import _chromium_available

    return _chromium_available()


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_filling_the_page_shows_errors_by_field_and_then_saves(running, db_path, tmp_path):
    from playwright.sync_api import sync_playwright

    port = running.server_address[1]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{port}/?t=t0k3n")

        page.get_by_role("heading", name="Pastas e opções").wait_for()
        assert page.get_by_text("Falta configurar").count() >= 1
        page.get_by_label("Pasta dos currículos em PDF").fill("pasta/relativa")
        page.get_by_label("Abas de candidatura abertas, no máximo").fill("99")
        page.get_by_role("button", name="Salvar tudo").click()
        page.get_by_text("Nada foi salvo").wait_for()
        assert page.locator(".campo.com-erro").count() == 2
        assert not config_path(db_path).exists()

        page.get_by_label("Pasta dos currículos em PDF").fill(str(tmp_path / "pdfs"))
        page.get_by_label("Abas de candidatura abertas, no máximo").fill("8")
        assert page.get_by_label("Pasta dos CSVs exportados").input_value() == str(db_path.parent / "exports")
        page.get_by_label("Login preferido nos sites de vagas").select_option("linkedin")
        page.get_by_label("Conta Google para login").fill("fulano@example.com")
        page.get_by_role("button", name="Salvar tudo").click()
        page.get_by_text("Tudo salvo").wait_for()
        assert page.locator(".campo.com-erro").count() == 0
        assert page.get_by_text("Falta configurar").count() == 0
        browser.close()

    assert resolve("resume_out", db_path) == (tmp_path / "pdfs", "config")
    assert resolve("max_open_tabs", db_path) == (8, "config") and resolve("login_method", db_path) == ("linkedin", "config")
    # padrões confirmados: o Claude não pergunta mais
    assert resolve("export_dir", db_path)[1] == "config" and resolve("master_resume", db_path)[1] == "config"
    assert (tmp_path / "pdfs").is_dir()


@pytest.fixture
def skill(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    examples = Path(__file__).resolve().parents[1] / "skill" / "candidaturas"
    folder = tmp_path / "skill"
    folder.mkdir()
    for name in ("perfil.example.md", "criterios-triagem.example.md"):
        shutil.copy(examples / name, folder / name)
    monkeypatch.setenv("VAGAS_SKILL_DIR", str(folder))
    monkeypatch.setenv("VAGAS_TRIAGE_CRITERIA", str(folder / "criterios-triagem.md"))
    return folder


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_profile_and_criteria_are_filled_in_one_go(skill, db_path):
    from playwright.sync_api import sync_playwright

    from vagas.triage import parse_criteria

    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            page.get_by_role("heading", name="Perfil para formulários").wait_for()
            assert page.get_by_label("Nome", exact=True).get_attribute("placeholder") == "Ex.: Fulano de Tal"
            assert page.get_by_text("Você digita no formulário").count() >= 2  # CPF e RG, sem campo

            page.get_by_label("Nome", exact=True).fill("Maria Teste")
            page.get_by_label("Incluir em bancos de talentos").select_option("não")
            page.get_by_label("Aderência mínima").fill("150")
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Nada foi salvo").wait_for()
            assert not (skill / "perfil.md").exists()

            page.get_by_label("Aderência mínima").fill("60")
            criteria = page.get_by_role("group", name="Cargos alvo")
            criteria.get_by_label("Engenheiro de ia").uncheck()
            page.get_by_role("group", name="Senioridades buscadas").get_by_label("Pleno").check()
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Tudo salvo").wait_for()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    profile = (skill / "perfil.md").read_text(encoding="utf-8")
    assert "- Nome: Maria Teste" in profile and "- Incluir em bancos de talentos: não" in profile
    assert "Fulano" not in profile
    saved = parse_criteria((skill / "criterios-triagem.md").read_text(encoding="utf-8"))
    assert saved.target_roles == ("data_scientist", "ml_engineer") and saved.search_seniorities == ("pleno",)
    assert saved.min_match == 60


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_enter_moves_to_the_next_field_and_diversity_offers_other(skill, db_path):
    from playwright.sync_api import sync_playwright

    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            requests = []
            page.on("request", lambda r: requests.append(r.method) if "/api/settings" in r.url else None)
            page.goto(server.url)
            page.get_by_role("heading", name="Perfil para formulários").wait_for()

            name = page.get_by_label("Nome", exact=True)
            name.fill("Maria Teste")
            name.press("Enter")
            assert page.evaluate("document.activeElement.id") == page.get_by_label("Telefone").get_attribute("id")
            page.wait_for_timeout(300)
            assert requests == ["GET"] and not (skill / "perfil.md").exists()  # Enter não salva

            page.get_by_label("Sexo", exact=True).select_option("Masculino")
            race = page.get_by_label("Raça/etnia", exact=True)
            race.select_option("__outra__")
            other = page.get_by_label("Raça/etnia: outra resposta")
            assert other.is_visible() and page.evaluate("document.activeElement.placeholder") == "Escreva a resposta"
            other.fill("Branco/Latino")
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Tudo salvo").wait_for()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    profile = (skill / "perfil.md").read_text(encoding="utf-8")
    assert "  - Sexo: Masculino\n" in profile and "  - Raça/etnia: Branco/Latino\n" in profile
    assert "  - Identidade de gênero: <...>\n" in profile and "- Nome: Maria Teste" in profile


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_salary_bands_are_edited_as_a_table(skill, db_path, monkeypatch):
    from playwright.sync_api import sync_playwright

    from vagas.salary_policy import parse_policy

    policy = skill / "politica-salarial.md"
    policy.write_text("# Política salarial\n\n- Modo: minimo\n- Multiplicador PJ: 1.4\n"
                      "- Remoto nacional (BRL, CLT): mínimo 8.000, máximo 12.000\n"
                      "- Internacional (USD): mínimo 3000\n", encoding="utf-8")
    monkeypatch.setenv("VAGAS_SALARY_POLICY", str(policy))
    monkeypatch.setattr("vagas.settings_form._reevaluate_salaries", lambda db: {"changed": []})
    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            bands = page.get_by_role("group", name="Faixas")
            bands.wait_for()
            first = bands.locator(".faixa").nth(0)
            first.get_by_label("Mínimo mensal").fill("")
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Nada foi salvo").wait_for()
            assert first.locator(".celula-min .erro").is_visible()

            first.get_by_label("Mínimo mensal").fill("9.500")
            bands.get_by_role("button", name="Adicionar faixa").click()
            new = bands.locator(".faixa").nth(2)
            new.get_by_label("Nome").fill("Híbrido em Campinas")
            new.get_by_label("Usar os valores da faixa").select_option("Remoto nacional")
            assert new.get_by_label("Mínimo mensal").is_disabled()
            new.locator("input[type=checkbox]").check()
            bands.locator(".faixa").nth(1).get_by_role("button", name="Remover faixa").click()
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Tudo salvo").wait_for()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    text = policy.read_text(encoding="utf-8")
    assert "- Remoto nacional (BRL, CLT): mínimo 9500, máximo 12000\n" in text
    assert "- Híbrido em Campinas (BRL, CLT): usar a faixa do Remoto nacional\n" in text
    assert "Internacional" not in text
    assert [b.label for b in parse_policy(text).bands] == ["Remoto nacional", "Híbrido em Campinas"]


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_languages_are_edited_as_rows(skill, db_path):
    import shutil
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    shutil.copy(Path(__file__).resolve().parents[1] / "skill" / "candidaturas" / "perfil.example.md", skill / "perfil.md")


def test_resume_sources_are_configured_in_the_panel(running, db_path, tmp_path):
    from playwright.sync_api import sync_playwright

    pdf = tmp_path / "Curriculo.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{running.server_address[1]}/?t=t0k3n")
        page.get_by_label("PDF do currículo (fonte do currículo geral)").fill(str(tmp_path / "nao-existe.pdf"))
        page.get_by_label("Perfil do LinkedIn (fonte do currículo geral)").fill("https://github.com/fulano")
        page.get_by_role("button", name="Salvar tudo").click()
        page.get_by_text("Nada foi salvo").wait_for()
        assert page.locator(".campo.com-erro").count() == 2

        page.get_by_label("PDF do currículo (fonte do currículo geral)").fill(str(pdf))
        page.get_by_label("Perfil do LinkedIn (fonte do currículo geral)").fill("linkedin.com/in/fulano/")
        page.get_by_role("button", name="Salvar tudo").click()
        page.get_by_text("Tudo salvo").wait_for()
        browser.close()

    assert resolve("resume_pdf", db_path) == (pdf, "config")
    assert resolve("linkedin_url", db_path) == ("https://www.linkedin.com/in/fulano", "config")


@pytest.fixture
def fake_vault(tmp_path, monkeypatch, skill):
    import shutil
    from pathlib import Path

    from test_sensitive import FakeBackend

    shutil.copy(Path(__file__).resolve().parents[1] / "skill" / "candidaturas" / "perfil.example.md",
                skill / "perfil.md")
    monkeypatch.setenv("VAGAS_SENSITIVE_FILE", str(tmp_path / "cofre.json"))
    monkeypatch.setattr("vagas.settings_files._vault_backend", FakeBackend)
    return tmp_path / "cofre.json"


def test_the_api_never_sends_a_vault_value_back(running, fake_vault):
    status, body = request(running, "POST", "/api/settings", {"vault": {"set": {"cpf": "529.982.247-25"}}}, TOKEN)
    _, page_data = request(running, "GET", "/api/settings", headers=TOKEN)

    assert status == 200 and json.loads(body)["saved"]
    for text in (body, page_data, fake_vault.read_text(encoding="utf-8")):
        assert "52998224725" not in text and "529.982.247-25" not in text


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_documents_are_stored_and_removed_without_showing_them(skill, db_path, fake_vault):
    from playwright.sync_api import sync_playwright

    from test_sensitive import FakeBackend
    from vagas.sensitive import Vault

    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            languages = page.get_by_role("group", name="Idiomas")
            languages.wait_for()
            rows = languages.locator(".idioma")
            assert rows.count() == 3
            assert rows.nth(0).get_by_label("Nível", exact=True).input_value() == "Nativo"
            assert rows.nth(1).get_by_label("Nível: outro").input_value() == "intermediário-avançado (B2, certificado)"

            rows.nth(2).get_by_role("button", name="Remover idioma").click()
            languages.get_by_role("button", name="Adicionar idioma").click()
            new = languages.locator(".idioma").nth(2)
            new.get_by_label("Idioma", exact=True).fill("libras")
            new.get_by_label("Nível", exact=True).select_option("__outra__")
            new.get_by_label("Nível: outro").fill("básico (curso livre)")
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Tudo salvo").wait_for()


            cpf = page.get_by_label("CPF", exact=True)
            cpf.wait_for()
            assert cpf.get_attribute("type") == "password"
            cpf.fill("111.111.111-11")
            show = page.get_by_role("button", name="Mostrar o que foi digitado em CPF")
            show.click()  # conferir o que foi digitado antes de salvar
            assert cpf.get_attribute("type") == "text" and cpf.input_value() == "111.111.111-11"
            page.get_by_role("button", name="Ocultar o que foi digitado em CPF").click()
            assert cpf.get_attribute("type") == "password"
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("CPF inválido").wait_for()

            page.get_by_label("CPF", exact=True).fill("529.982.247-25")
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Tudo salvo").wait_for()
            assert page.get_by_label("CPF", exact=True).input_value() == ""
            assert page.get_by_text("Guardado no cofre").count() == 1
            assert "52998224725" not in page.content()

            page.get_by_role("button", name="Remover do cofre").click()
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Tudo salvo").wait_for()
            assert page.get_by_text("Guardado no cofre").count() == 0
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    assert ("- Idiomas: português (nativo), inglês intermediário-avançado (B2, certificado), libras (básico (curso livre))\n"
            in (skill / "perfil.md").read_text(encoding="utf-8"))


    assert Vault(fake_vault, FakeBackend()).list() == []
    assert "- CPF: informar manualmente" in (skill / "perfil.md").read_text(encoding="utf-8")


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_master_resume_is_edited_by_section(db_path):
    import yaml
    from playwright.sync_api import sync_playwright

    from resume_fixture import fictitious_resume
    from vagas.db import connect
    from vagas.resume_repo import ResumeStore, default_draft_path

    conn = connect(db_path)
    ResumeStore(conn, default_draft_path(db_path)).save_master_draft(fictitious_resume())
    conn.close()
    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            page.get_by_role("heading", name="Currículo geral").wait_for()
            resume = page.locator("#secao-resume")
            resume.get_by_text("Experiências", exact=True).click()
            item = resume.locator("details.cv-item").filter(has_text="Quantitative Analyst").first
            item.locator("summary").first.click()
            item.get_by_label("Empresa *").fill("")
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Nada foi salvo").wait_for()
            assert item.get_by_text("Campo obrigatório.").is_visible()

            item.get_by_label("Empresa *").fill("Acme Analytics Ltd")
            item.get_by_role("button", name="Adicionar parágrafo").click()
            item.locator("details.cv-item").last.get_by_label("Texto *").fill("Automated monthly reports.")
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Tudo salvo").wait_for()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    draft = yaml.safe_load(default_draft_path(db_path).read_text(encoding="utf-8"))
    analyst = next(e for e in draft["experience"] if e["id"] == "exp-acme-analyst")
    assert analyst["company"] == "Acme Analytics Ltd"
    assert analyst["paragraphs"][-1] == {"id": "exp-acme-analyst-p2", "text": "Automated monthly reports."}


def test_approving_through_the_panel_needs_token_origin_and_the_current_draft(running, db_path):
    from resume_fixture import fictitious_resume
    from vagas.db import connect
    from vagas.resume_repo import ResumeStore, default_draft_path

    conn = connect(db_path)
    store = ResumeStore(conn, default_draft_path(db_path))
    store.save_master_draft(fictitious_resume())
    _, body = request(running, "GET", "/api/settings", headers=TOKEN)
    fingerprint = json.loads(body)["sections"]["resume"]["hash"]
    port = running.server_address[1]

    no_token, _ = request(running, "POST", "/api/resume/approve", {"hash": fingerprint})
    other_site, _ = request(running, "POST", "/api/resume/approve", {"hash": fingerprint},
                            {**TOKEN, "Origin": "https://ataque.example.com"})
    stale, stale_body = request(running, "POST", "/api/resume/approve", {"hash": "antigo"}, TOKEN)
    ok, ok_body = request(running, "POST", "/api/resume/approve", {"hash": fingerprint},
                         {**TOKEN, "Origin": f"http://127.0.0.1:{port}"})

    assert (no_token, other_site, stale, ok) == (403, 403, 409, 200)
    assert "Recarregue" in json.loads(stale_body)["error"] and json.loads(ok_body)["created"]
    assert store.get_master_resume()["resume"]["basics"]["name"] == "Fulana de Tal"
    conn.close()


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_master_resume_is_approved_from_the_panel_after_a_confirmation(db_path):
    from playwright.sync_api import sync_playwright

    from resume_fixture import fictitious_resume
    from vagas.db import connect
    from vagas.resume_repo import ResumeStore, default_draft_path

    conn = connect(db_path)
    store = ResumeStore(conn, default_draft_path(db_path))
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    changed = fictitious_resume()
    changed["experience"][0]["title"] = "AI Engineering Coordinator"
    store.save_master_draft(changed, overwrite=True)
    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            area = page.locator(".aprovacao")
            area.wait_for()
            assert "AI Engineering Coordinator" in area.inner_text() and "alterado (Cargo)" in area.inner_text()

            page.get_by_role("button", name="Aprovar o rascunho").click()
            page.get_by_role("button", name="Cancelar").click()
            assert store.get_master_resume()["resume"]["experience"][0]["title"] != "AI Engineering Coordinator"

            page.get_by_role("button", name="Aprovar o rascunho").click()
            page.get_by_role("button", name="Confirmar aprovação").click()
            page.get_by_text("Currículo geral aprovado").wait_for()
            assert page.get_by_role("button", name="Aprovar o rascunho").is_disabled()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    assert store.get_master_resume()["resume"]["experience"][0]["title"] == "AI Engineering Coordinator"
    conn.close()


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_unsaved_resume_edits_block_the_approval(db_path):
    from playwright.sync_api import sync_playwright

    from resume_fixture import fictitious_resume
    from vagas.db import connect
    from vagas.resume_repo import ResumeStore, default_draft_path

    conn = connect(db_path)
    store = ResumeStore(conn, default_draft_path(db_path))
    store.save_master_draft(fictitious_resume())
    conn.close()
    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            page.get_by_label("Headline").fill("Mudança não salva")
            page.get_by_role("button", name="Aprovar o rascunho").click()
            page.get_by_text("alterações não salvas no currículo").wait_for()
            assert page.get_by_role("button", name="Confirmar aprovação").is_hidden()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_profile_shows_resume_experiences_and_computed_years(skill, db_path):
    import shutil
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    from resume_fixture import fictitious_resume
    from vagas.db import connect
    from vagas.resume_repo import ResumeStore, default_draft_path

    shutil.copy(Path(__file__).resolve().parents[1] / "skill" / "candidaturas" / "perfil.example.md", skill / "perfil.md")
    conn = connect(db_path)
    store = ResumeStore(conn, default_draft_path(db_path))
    store.save_master_draft(fictitious_resume())
    store.approve_master()
    conn.close()
    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            page.get_by_text("Experiências do currículo geral", exact=True).wait_for()
            assert page.get_by_text("Quantitative Analyst — Acme Analytics").is_visible()
            assert page.get_by_text("Total:").is_visible()
            years = page.get_by_label("Anos de experiência a declarar")
            assert "calculados pelo currículo geral" in years.get_attribute("placeholder")
            years.fill("8")
            page.get_by_role("button", name="Salvar tudo").click()
            page.get_by_text("Tudo salvo").wait_for()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    assert "- Anos de experiência a declarar: 8\n" in (skill / "perfil.md").read_text(encoding="utf-8")


def test_jobs_api_lists_filters_and_details_with_the_token(running, db_path):
    from vagas.db import connect
    from vagas.repo import Repo

    conn = connect(db_path)
    app = Repo(conn).add_application(company="Acme", role="Data Scientist", source="gupy", status="a_aplicar",
                                     url="https://acme.gupy.io/jobs/1")["application"]
    conn.close()

    denied, _ = request(running, "GET", "/api/jobs")
    ok, body = request(running, "GET", "/api/jobs?status=a_aplicar&text=data", headers=TOKEN)
    detail, detail_body = request(running, "GET", f"/api/jobs/{app['id']}", headers=TOKEN)
    bad, bad_body = request(running, "GET", "/api/jobs?status=contratado", headers=TOKEN)
    missing, _ = request(running, "GET", "/api/jobs/999", headers=TOKEN)

    assert denied == 403 and (ok, detail, bad, missing) == (200, 200, 400, 404)
    assert json.loads(body)["items"][0]["role"] == "Data Scientist"
    assert json.loads(detail_body)["application"]["company"] == "Acme"
    assert "status" in json.loads(bad_body)["error"]


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_jobs_tab_lists_filters_and_opens_the_detail(db_path):
    from playwright.sync_api import expect, sync_playwright

    from vagas.db import connect
    from vagas.repo import Repo

    conn = connect(db_path)
    repo = Repo(conn)
    for n, (company, role, status) in enumerate([("Acme", "Data Scientist", "a_aplicar"),
                                                 ("Beta", "ML Engineer", "a_aplicar"),
                                                 ("Gama", "Data Analyst", "aplicada")], start=1):
        app = repo.add_application(company=company, role=role, source="gupy", status=status,
                                   url=f"https://example.com/vagas/{n}", description="<b>Python</b> e SQL")["application"]
        repo.set_match(app["id"], 50 + n * 10, {"matched": ["Python"], "missing": ["Spark"]})
    conn.close()
    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            page.get_by_role("link", name="Vagas").click()
            page.get_by_role("button", name="A aplicar: 2").wait_for()
            assert page.locator(".tabela-vagas tbody tr").count() == 3

            page.get_by_role("button", name="A aplicar: 2").click()
            expect(page.locator(".tabela-vagas tbody tr")).to_have_count(2)  # a CSP bloqueia wait_for_function
            assert page.locator(".tabela-vagas tbody tr").first.inner_text().strip().startswith("ML Engineer")  # maior aderência
            page.get_by_role("button", name="Detalhes de Data Scientist — Acme").click()
            detail = page.locator(".detalhe")
            detail.wait_for()
            assert "Termos ausentes" in detail.inner_text() and "Spark" in detail.inner_text()
            detail.get_by_text("Descrição da vaga").click()
            assert detail.locator(".descricao").inner_text() == "<b>Python</b> e SQL"  # texto, nunca HTML
            assert page.get_by_role("button", name="Salvar tudo").is_hidden()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def test_job_actions_need_token_and_origin_and_follow_the_rules(running, db_path):
    from vagas.db import connect
    from vagas.repo import Repo

    conn = connect(db_path)
    repo = Repo(conn)
    a = repo.add_application(company="Acme", role="Data Scientist", source="gupy", status="a_aplicar",
                             url="https://example.com/vagas/1")["application"]
    b = repo.add_application(company="Beta", role="ML Engineer", source="gupy", status="a_aplicar",
                             url="https://example.com/vagas/2")["application"]
    port = running.server_address[1]
    origin = {**TOKEN, "Origin": f"http://127.0.0.1:{port}"}

    no_token, _ = request(running, "POST", "/api/jobs/action", {"action": "discard", "ids": [a["id"]], "reason": "x"})
    other_site, _ = request(running, "POST", "/api/jobs/action", {"action": "discard", "ids": [a["id"]], "reason": "x"},
                            {**TOKEN, "Origin": "https://ataque.example.com"})
    no_reason, no_reason_body = request(running, "POST", "/api/jobs/action",
                                        {"action": "discard", "ids": [a["id"], b["id"]], "reason": ""}, origin)
    ok, ok_body = request(running, "POST", "/api/jobs/action",
                          {"action": "discard", "ids": [a["id"], b["id"]], "reason": "sem retorno"}, origin)

    assert (no_token, other_site, no_reason, ok) == (403, 403, 400, 200)
    assert "motivo" in json.loads(no_reason_body)["error"]
    assert [i["status"] for i in json.loads(ok_body)["items"]] == ["descartada", "descartada"]
    assert repo.get(a["id"])["discard_reason"] == "sem retorno"
    conn.close()


@pytest.mark.skipif(not _chromium(), reason="Playwright com Chromium não instalado")
def test_jobs_are_updated_discarded_and_reopened_from_the_panel(db_path):
    from playwright.sync_api import expect, sync_playwright

    from vagas.db import connect
    from vagas.repo import Repo

    conn = connect(db_path)
    repo = Repo(conn)
    ids = {}
    for n, (company, role, status) in enumerate([("Acme", "Data Scientist", "aplicada"),
                                                 ("Beta", "ML Engineer", "a_aplicar"),
                                                 ("Gama", "Data Analyst", "a_aplicar")], start=1):
        ids[company] = repo.add_application(company=company, role=role, source="gupy", status=status,
                                            url=f"https://example.com/vagas/{n}")["application"]["id"]
    server = panel.make_server(db_path, token="t0k3n")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url + "#vagas")
            page.get_by_role("button", name="Detalhes de Data Scientist — Acme").click()
            page.get_by_label("Etapa").select_option("tecnica")
            page.get_by_label("Anotação no histórico").fill("Entrevista na sexta")
            page.get_by_role("button", name="Salvar alterações").click()
            page.get_by_text("Vaga atualizada.").wait_for()

            page.get_by_label("Selecionar ML Engineer — Beta").check()
            page.get_by_label("Selecionar Data Analyst — Gama").check()
            page.get_by_role("button", name="Descartar selecionadas").click()
            page.get_by_text("Informe o motivo do descarte.").wait_for()  # sem motivo: nada descartado
            page.get_by_label("Motivo do descarte das vagas selecionadas").fill("sem retorno")
            page.get_by_role("button", name="Descartar selecionadas").click()
            page.get_by_text("2 vaga(s) descartada(s).").wait_for()

            page.get_by_role("button", name="Detalhes de Data Analyst — Gama").click()
            page.get_by_label("Motivo para reabrir").fill("ainda interessa")
            page.get_by_role("button", name="Reabrir a vaga").click()
            page.get_by_text("Vaga reaberta.").wait_for()
            expect(page.get_by_role("button", name="A aplicar: 1")).to_be_visible()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()

    assert repo.get(ids["Acme"])["status"] == "tecnica"
    assert repo.get_history(ids["Acme"])["events"][-1]["note"] == "Entrevista na sexta"
    assert repo.get(ids["Beta"])["status"] == "descartada" and repo.get(ids["Gama"])["status"] == "a_aplicar"
    conn.close()
