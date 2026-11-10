"""Painel local de configuração: servidor HTTP real numa porta efêmera, só em 127.0.0.1, com token."""

import http.client
import json
import re
import threading

import pytest

from vagas import panel
from vagas.config import config_path


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
    assert str(tmp_path / "csv") in config_path(db_path).read_text(encoding="utf-8")


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

    saved = config_path(db_path).read_text(encoding="utf-8")
    assert f'resume_out = "{tmp_path / "pdfs"}"'.replace("\\", "\\\\") in saved
    assert "max_open_tabs = 8" in saved and 'login_method = "linkedin"' in saved
    assert "export_dir" in saved and "master_resume" in saved  # padrões confirmados: o Claude não pergunta mais
    assert (tmp_path / "pdfs").is_dir()
