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

# Localiza a lista principal da página de detalhes a partir do título da seção: dentro de <main>,
# o primeiro texto com um ano depois do título; entre os ancestrais desse texto até o ancestral comum
# com o título, a lista é o elemento cujos filhos mais contêm anos (cada filho é um item).
_FIND_LIST = r"""
const findList = (title) => {
  const root = document.querySelector("main") || document.body;
  const year = /\b(19|20)\d{2}\b/;
  const heading = [...root.querySelectorAll("h1, h2, h3, span, div, p")]
    .find(e => e.innerText && e.innerText.trim() === title && ![...e.children].some(c => c.innerText && c.innerText.trim() === title));
  if (!heading) return null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = null, n;
  while ((n = walker.nextNode())) {
    if (n.parentElement.closest("script, style, noscript")) continue;
    if (year.test(n.textContent) && (heading.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING)) { node = n; break; }
  }
  if (!node) return null;
  let top = node.parentElement;
  while (top && !top.contains(heading)) top = top.parentElement;
  const path = [];
  for (let e = node.parentElement; e && e !== top; e = e.parentElement) path.push(e);
  path.push(top);
  const score = e => [...e.children].filter(c => !c.contains(heading) && year.test(c.innerText || "")).length;
  // A lista mais externa com 2+ itens (assim uma empresa com vários cargos conta como um item);
  // com um item só, o elemento de maior pontuação mais próximo do título.
  const fromTop = path.slice().reverse();
  let best = fromTop.find(e => score(e) >= 2);
  if (!best) { best = top; for (const e of fromTop) if (score(e) > score(best)) best = e; }
  return {list: best, heading};
};
const linesOf = e => (e.innerText || "").split("\n").map(s => s.trim()).filter(Boolean);
const linksOf = e => [...e.querySelectorAll("a[href]")].map(a => ({text: a.innerText.trim(), href: a.href}));
// Lista interna de um item (ex.: vários cargos na mesma empresa): descendente com 2+ filhos com ano.
const innerList = item => {
  // Cargos têm período ("Aug 2020 - Sep 2021", "May 2024 - Present"); anos soltos em descrições não contam.
  const period = /\b[A-Z][a-z]{2} (19|20)\d{2} [-–] ([A-Z][a-z]{2} (19|20)\d{2}|Present)/;
  let best = null, bestCount = 1;
  for (const e of item.querySelectorAll("*")) {
    const count = [...e.children].filter(c => period.test(c.innerText || "")).length;
    if (count > bestCount) { best = e; bestCount = count; }
  }
  return best;
};
"""

# Separa os itens da lista em blocos {lines, links}; a interpretação fica em linkedin_parse.
BLOCKS_JS = "(title) => {" + _FIND_LIST + r"""
  const found = findList(title);
  if (!found) return [];
  return [...found.list.children].filter(c => !c.contains(found.heading)).map(child => {
    const lines = linesOf(child), inner = innerList(child);
    if (!inner) return {lines, links: linksOf(child)};
    const roles = [...inner.children].map(r => ({lines: linesOf(r), links: linksOf(r)})).filter(r => r.lines.length);
    const roleLines = roles.reduce((n, r) => n + r.lines.length, 0);
    return {lines: lines.slice(0, Math.max(lines.length - roleLines, 0)), links: [], roles};
  }).filter(block => block.lines.length || (block.roles && block.roles.length));
}"""

# Traz o último item da lista para a tela (dispara o carregamento do próximo lote) e devolve quantos há.
SCROLL_JS = "(title) => {" + _FIND_LIST + r"""
  window.scrollTo(0, document.body.scrollHeight);
  const found = findList(title);
  if (!found) return 0;
  const items = [...found.list.children].filter(c => !c.contains(found.heading));
  if (items.length) items[items.length - 1].scrollIntoView({block: "end"});
  return items.length;
}"""

# Título da seção em cada página de detalhes (chave = nome da seção no currículo geral).
SECTION_TITLES = {
    "certifications": "Licenses & certifications",
    "experience": "Experience",
    "education": "Education",
    "volunteering": "Volunteering",
}
SECTION_PAGES = {"volunteering": "volunteering-experiences"}
_EXPANDERS = re.compile(r"^(…|\.\.\.)\s*(see )?more$|^see more$", re.IGNORECASE)


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


def _scroll_to_end(page, marker: str | None = None, max_rounds: int = 80) -> None:
    """Carrega a lista inteira: traz o último item para a tela e clica em "Show more" até a quantidade de
    itens (ou, sem marcador, a altura da página) ficar igual em três leituras seguidas."""
    stable, last = 0, -1
    for _ in range(max_rounds):
        size = page.evaluate(SCROLL_JS, marker) if marker else None
        if not marker:
            page.mouse.wheel(0, 4000)
        page.wait_for_timeout(2000)
        button = page.get_by_role("button", name=_SHOW_MORE)
        if button.count() and button.first.is_visible():
            button.first.click()
            page.wait_for_timeout(2000)
            stable = 0
            continue
        current = page.evaluate(SCROLL_JS, marker) if marker else page.evaluate("document.body.scrollHeight")
        current = max(current, size or 0)
        stable = stable + 1 if current == last else 0
        last = current
        if stable >= 3:
            return


def _expand_descriptions(page) -> None:
    """Clica nos "… more" das descrições cortadas, para extrair o texto inteiro. Na interface atual
    eles nem sempre são botões; o clique vai no elemento que mostra o texto."""
    for _ in range(100):
        expanders = [e for e in page.get_by_text(_EXPANDERS).all() if e.is_visible()]
        if not expanders:
            return
        expanders[0].click()
        page.wait_for_timeout(400)


def _open(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    if is_blocked(page.url):
        raise LinkedInError(
            "O LinkedIn pediu login ou verificação de segurança. Rode `python -m vagas.linkedin login`, "
            "resolva a verificação na janela e tente de novo."
        )


class LinkedInReader:
    """Lê as páginas de detalhes do perfil com a sessão salva pelo comando de login."""

    def __init__(self, headless: bool | None = None):
        self.headless = os.environ.get("VAGAS_LINKEDIN_HEADLESS", "1") != "0" if headless is None else headless

    def read_sections(self, url: str, sections: tuple[str, ...]) -> dict[str, list[dict]]:
        urls = detail_urls(url)
        result = {}
        with _playwright() as p:
            context = _browser(p, headless=self.headless)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                for section in sections:
                    _open(page, urls[SECTION_PAGES.get(section, section)])
                    _scroll_to_end(page, SECTION_TITLES[section])
                    _expand_descriptions(page)
                    result[section] = page.evaluate(BLOCKS_JS, SECTION_TITLES[section])
            finally:
                context.close()
        return result


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
