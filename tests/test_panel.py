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
