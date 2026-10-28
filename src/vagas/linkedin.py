"""Navegador para o perfil do LinkedIn do próprio usuário (extra opcional "linkedin", com Playwright).

Uso:
    python -m vagas.linkedin login                    # abre o navegador para o usuário entrar (uma vez)
    python -m vagas.linkedin capture <URL do perfil>  # salva o HTML do perfil e das páginas de detalhes

A sessão fica num perfil de navegador persistente na pasta de dados (permissões restritas); a senha
nunca passa por aqui. Sem técnicas de disfarce: diante de login, checkpoint ou captcha, o comando
para e pede ação do usuário.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from vagas.db import default_db_path

DETAIL_SECTIONS = ("experience", "education", "certifications", "volunteering-experiences", "languages", "skills")
_BLOCKED = re.compile(r"/(login|checkpoint|authwall|uas/login|signup)\b")
_SHOW_MORE = re.compile(r"show more|exibir mais|ver mais|mostrar mais", re.IGNORECASE)


class LinkedInError(RuntimeError):
    """Problema que exige ação do usuário (login, checkpoint, URL inválida)."""


def profile_base(url: str) -> str:
    """URL canônica do perfil: https://www.linkedin.com/in/<slug>/."""
    match = re.search(r"linkedin\.com/in/([^/?#]+)", url or "")
    if not match:
        raise LinkedInError(f"{url!r} não é a URL de um perfil do LinkedIn (esperado .../in/<perfil>/).")
    return f"https://www.linkedin.com/in/{match.group(1)}/"


def detail_urls(url: str) -> dict[str, str]:
    base = profile_base(url)
    return {section: f"{base}details/{section}/" for section in DETAIL_SECTIONS}


def is_blocked(url: str) -> bool:
    """A página atual é de login, checkpoint ou verificação (sessão ausente ou desafio de segurança)."""
    return bool(_BLOCKED.search(url))


def data_dir() -> Path:
    return default_db_path().parent


def browser_profile_dir() -> Path:
    path = Path(os.environ.get("VAGAS_LINKEDIN_PROFILE_DIR") or data_dir() / "linkedin-browser")
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _browser(playwright, headless: bool):
    return playwright.chromium.launch_persistent_context(str(browser_profile_dir()), headless=headless,
                                                         viewport={"width": 1280, "height": 900})


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise LinkedInError(
            "Playwright não instalado. Rode: uv pip install -e '.[linkedin]' && python -m playwright install chromium"
        ) from exc
    return sync_playwright()


def login(timeout_minutes: int = 10) -> None:
    with _playwright() as p:
        context = _browser(p, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.linkedin.com/login")
        print("Entre na sua conta do LinkedIn na janela aberta (inclusive 2FA, se pedir). Aguardando...")
        deadline = datetime.now().timestamp() + timeout_minutes * 60
        while datetime.now().timestamp() < deadline:
            if not is_blocked(page.url) and "linkedin.com" in page.url and "/login" not in page.url:
                print("Login concluído; sessão salva em", browser_profile_dir())
                context.close()
                return
            page.wait_for_timeout(2000)
        context.close()
        raise LinkedInError("Tempo esgotado esperando o login; rode o comando de novo.")


def _scroll_to_end(page, max_rounds: int = 60) -> None:
    """Rola e clica em "Show more" até a página parar de crescer em duas leituras seguidas."""
    stable, last_height = 0, -1
    for _ in range(max_rounds):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1500)
        button = page.get_by_role("button", name=_SHOW_MORE)
        if button.count() and button.first.is_visible():
            button.first.click()
            page.wait_for_timeout(1500)
            stable = 0
            continue
        height = page.evaluate("document.body.scrollHeight")
        stable = stable + 1 if height == last_height else 0
        last_height = height
        if stable >= 2:
            return


def _open(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    if is_blocked(page.url):
        raise LinkedInError(
            "O LinkedIn pediu login ou verificação de segurança. Rode `python -m vagas.linkedin login`, "
            "resolva a verificação na janela e tente de novo."
        )


def capture(url: str, out: Path | None = None, headless: bool = False) -> Path:
    """Salva o HTML da página do perfil e das páginas de detalhes, roladas até o fim."""
    urls = {"profile": profile_base(url), **detail_urls(url)}
    out = out or data_dir() / "linkedin-capture" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    with _playwright() as p:
        context = _browser(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for name, page_url in urls.items():
                _open(page, page_url)
                _scroll_to_end(page)
                (out / f"{name}.html").write_text(page.content(), encoding="utf-8")
                print(f"  {name}: salvo")
        finally:
            context.close()
    (out / "meta.json").write_text(json.dumps({"urls": urls, "captured_at": datetime.now().isoformat()}, indent=2))
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m vagas.linkedin", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="abre o navegador para entrar no LinkedIn (uma vez)")
    cap = sub.add_parser("capture", help="salva o HTML do perfil e das páginas de detalhes")
    cap.add_argument("url")
    cap.add_argument("--out", type=Path)
    cap.add_argument("--headless", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "login":
            login()
        else:
            print("Pasta da captura:", capture(args.url, args.out, args.headless))
    except LinkedInError as exc:
        sys.exit(f"ERRO: {exc}")


if __name__ == "__main__":
    main()
