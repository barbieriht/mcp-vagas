"""Painel local de configuração no navegador: python -m vagas.panel.

Só HTTP: serve a página e repassa o formulário para vagas.settings_form, onde fica a regra. Segurança:
- escuta só em 127.0.0.1, numa porta livre;
- um token aleatório por execução vai no link (?t=...) e é exigido em toda chamada da API;
- os cabeçalhos Host e Origin são conferidos (contra DNS rebinding e envio por outro site);
- a página não carrega nada da internet (CSP restritiva) e não manda o link adiante (Referrer-Policy).
Um segundo `python -m vagas.panel` reaproveita o painel aberto (estado em painel.json, ao lado do banco).
Fecha sozinho depois de um tempo sem uso. Não é o servidor MCP: aqui o stdout é livre.
"""

import argparse
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from vagas import settings_form, system
from vagas.db import default_db_path
from vagas.repo import VagasError

log = logging.getLogger(__name__)
MAX_BODY = 1024 * 1024
STATE_NAME = "painel.json"
STATIC = {"/panel.js": "text/javascript; charset=utf-8", "/jobs.js": "text/javascript; charset=utf-8",
          "/panel.css": "text/css; charset=utf-8"}
_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "form-action 'none'; frame-ancestors 'none'; base-uri 'none'")


def _asset(name: str) -> bytes:
    return files("vagas").joinpath("templates", "panel", name).read_bytes()


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, db_path: Path, token: str, port: int = 0):
        super().__init__(("127.0.0.1", port), _Handler)
        self.db_path = db_path
        self.token = token
        self.last_seen = time.monotonic()
        self.save_lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?t={self.token}"


def make_server(db_path: Path | str | None = None, token: str | None = None, port: int = 0) -> PanelServer:
    db = Path(db_path) if db_path is not None else default_db_path()
    return PanelServer(db, token or secrets.token_urlsafe(24), port)


class _Handler(BaseHTTPRequestHandler):
    server: PanelServer
    server_version = "mcp-vagas-painel"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # nada de URLs com o token no terminal
        log.debug("painel: %s", self.command)

    # --- conferências -----------------------------------------------------------------------
    def _origins(self) -> tuple[str, ...]:
        port = self.server.server_address[1]
        return (f"127.0.0.1:{port}", f"localhost:{port}")

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self._origins()

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in tuple(f"http://{o}" for o in self._origins())

    def _token_ok(self, given: str | None) -> bool:
        return secrets.compare_digest((given or "").encode(), self.server.token.encode())

    # --- respostas --------------------------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", _CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _denied(self) -> None:
        self._send(403, "Acesso negado. Abra o painel pelo link que o comando python -m vagas.panel mostra."
                   .encode("utf-8"), "text/plain; charset=utf-8")

    # --- rotas ------------------------------------------------------------------------------
    def do_GET(self) -> None:
        self.server.last_seen = time.monotonic()
        if not self._host_ok():
            return self._denied()
        parts = urlsplit(self.path)
        if parts.path in STATIC:
            return self._send(200, _asset(parts.path.lstrip("/")), STATIC[parts.path])
        if parts.path == "/":
            if not self._token_ok(parse_qs(parts.query).get("t", [None])[0]):
                return self._denied()
            return self._send(200, _asset("index.html"), "text/html; charset=utf-8")
        if not self._token_ok(self.headers.get("X-Panel-Token")):
            return self._denied()
        if parts.path == "/api/ping":
            return self._json(200, {"ok": True})
        if parts.path == "/api/settings":
            try:
                return self._json(200, settings_form.load(self.server.db_path))
            except VagasError as exc:
                return self._json(500, {"error": str(exc)})
        if parts.path == "/api/jobs" or parts.path.startswith("/api/jobs/"):
            return self._jobs(parts)
        if parts.path == "/api/searches":
            return self._searches(parts)
        return self._send(404, b"", "text/plain")

    def do_POST(self) -> None:
        self.server.last_seen = time.monotonic()
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = -1
        if not (self._host_ok() and self._origin_ok() and self._token_ok(self.headers.get("X-Panel-Token"))):
            self.close_connection = True
            self._denied()
            return self._discard(size)
        route = urlsplit(self.path).path
        if route not in ("/api/settings", "/api/resume/approve", "/api/jobs/action"):
            self.close_connection = True
            self._send(404, b"", "text/plain")
            return self._discard(size)
        if size < 0 or size > MAX_BODY:
            self.close_connection = True
            self._json(413, {"error": "Formulário grande demais."})
            return self._discard(size)
        try:
            data = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json(400, {"error": "Formulário inválido (JSON)."})
        with self.server.save_lock:  # duas abas salvando juntas não se misturam
            try:
                if route == "/api/resume/approve":
                    return self._approve(data)
                if route == "/api/jobs/action":
                    return self._job_action(data)
                return self._json(200, settings_form.save(data, self.server.db_path))
            except VagasError as exc:
                return self._json(500, {"error": str(exc)})

    def _jobs(self, parts: Any) -> None:
        """Vagas registradas: GET /api/jobs?filtros (lista) e GET /api/jobs/<id> (detalhe). Só leitura."""
        from vagas import jobs_view
        from vagas.db import connect

        conn = connect(self.server.db_path)
        try:
            if parts.path == "/api/jobs":
                filters = {k: v[-1] for k, v in parse_qs(parts.query).items()}
                return self._json(200, jobs_view.list_jobs(conn, filters))
            tail = parts.path.removeprefix("/api/jobs/")
            if not tail.isdigit():
                return self._json(404, {"error": "Vaga não encontrada."})
            return self._json(200, jobs_view.job_detail(conn, int(tail)))
        except VagasError as exc:
            return self._json(400 if parts.path == "/api/jobs" else 404, {"error": str(exc)})
        finally:
            conn.close()

    def _searches(self, parts: Any) -> None:
        """Buscas feitas e buscas em lote: GET /api/searches?source=. Só leitura."""
        from vagas import jobs_view
        from vagas.db import connect

        conn = connect(self.server.db_path)
        try:
            filters = {k: v[-1] for k, v in parse_qs(parts.query).items()}
            return self._json(200, jobs_view.list_searches(conn, filters))
        except VagasError as exc:
            return self._json(400, {"error": str(exc)})
        finally:
            conn.close()

    def _job_action(self, data: Any) -> None:
        """Ações sobre as vagas: {action: update|discard|reopen, id | ids, ...}, pelas regras do Repo."""
        from vagas import jobs_view
        from vagas.db import connect

        if not isinstance(data, dict):
            return self._json(400, {"error": "Ação inválida."})
        action = data.get("action")
        conn = connect(self.server.db_path)
        try:
            if action == "update" and isinstance(data.get("id"), int):
                return self._json(200, {"items": [jobs_view.update_job(conn, data["id"], data)]})
            if action == "discard" and isinstance(data.get("ids"), list):
                return self._json(200, {"items": jobs_view.discard_jobs(conn, data["ids"], str(data.get("reason") or ""))})
            if action == "reopen" and isinstance(data.get("id"), int):
                return self._json(200, {"items": [jobs_view.reopen_job(conn, data["id"], str(data.get("reason") or ""))]})
            return self._json(400, {"error": "Ação desconhecida."})
        except VagasError as exc:
            return self._json(400, {"error": str(exc)})
        finally:
            conn.close()

    def _approve(self, data: Any) -> None:
        """Aprova o rascunho do currículo geral que o usuário viu (mesma impressão digital)."""
        from vagas import settings_resume

        fingerprint = data.get("hash") if isinstance(data, dict) else None
        try:
            result = settings_resume.approve(self.server.db_path, fingerprint)
        except VagasError as exc:
            return self._json(409, {"error": str(exc)})
        return self._json(200, {"approved": True, **result, "settings": settings_form.load(self.server.db_path)})


    def _discard(self, size: int) -> None:
        """Lê e joga fora o corpo recusado (até um limite), para fechar a conexão sem reset: no Windows,
        fechar com dados não lidos aborta a conexão antes de o navegador ler a resposta."""
        remaining = min(max(size, 0), 8 * MAX_BODY)
        self.connection.settimeout(1)
        try:
            while remaining > 0 and (chunk := self.rfile.read1(min(remaining, 65536))):
                remaining -= len(chunk)
        except OSError:
            pass


# --- estado do painel aberto -----------------------------------------------------------------

def _state_path(db_path: Path | str | None) -> Path:
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / STATE_NAME


def remember(server: PanelServer, db_path: Path | str | None = None) -> Path:
    """Grava a porta e o token do painel aberto (só o dono do arquivo lê), para reaproveitá-lo."""
    path = _state_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"port": server.server_address[1], "token": server.token, "pid": os.getpid()}, f)
    if os.name != "nt":
        os.chmod(path, 0o600)
    return path


def running_url(db_path: Path | str | None = None) -> str | None:
    """Link do painel já aberto, ou None se não houver (ou se o estado gravado for de um painel fechado)."""
    try:
        state = json.loads(_state_path(db_path).read_text(encoding="utf-8"))
        port, token = int(state["port"]), str(state["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    request = Request(f"http://127.0.0.1:{port}/api/ping", headers={"X-Panel-Token": token})
    try:
        with urlopen(request, timeout=2) as response:
            if response.status == 200:
                return f"http://127.0.0.1:{port}/?t={token}"
    except OSError:
        pass
    return None


def launch_detached(db_path: Path | str | None = None) -> subprocess.Popen:
    """Abre o painel num processo à parte, sem navegador e sem herdar o stdout de quem chamou (o do MCP)."""
    db = Path(db_path) if db_path is not None else default_db_path()
    return subprocess.Popen([sys.executable, "-m", "vagas.panel", "--sem-navegador"],
                            env={**os.environ, "VAGAS_DB": str(db)}, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            **system.detached_process_options())


def ensure_running(db_path: Path | str | None = None, launcher: Any = None, timeout: float = 15.0) -> tuple[str, bool]:
    """Link do painel, abrindo-o se preciso. Devolve (url, started): started diz se foi aberto agora."""
    if url := running_url(db_path):
        return url, False
    try:
        (launcher or launch_detached)(db_path)
    except OSError as exc:
        raise VagasError(f"Não foi possível abrir o painel: {exc}. Rode python -m vagas.panel no terminal.") from exc
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if url := running_url(db_path):
            return url, True
        time.sleep(0.2)
    raise VagasError("O painel não respondeu a tempo. Rode python -m vagas.panel no terminal e use o link que ele "
                     "mostrar.")


def open_browser(url: str) -> None:
    """Abre o navegador padrão; no WSL, o do Windows."""
    if system.IN_WSL:
        subprocess.run(["cmd.exe", "/c", "start", "", url], cwd="/mnt/c", check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def _close_when_idle(server: PanelServer, idle_seconds: float) -> None:
    while True:
        time.sleep(min(30.0, idle_seconds))
        if time.monotonic() - server.last_seen > idle_seconds:
            server.shutdown()
            return


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m vagas.panel", description="Painel de configuração do mcp-vagas.")
    parser.add_argument("--sem-navegador", action="store_true", help="só mostra o link, sem abrir o navegador")
    parser.add_argument("--em-segundo-plano", action="store_true",
                        help="abre o painel num processo à parte e sai (usado pelos instaladores)")
    parser.add_argument("--minutos-sem-uso", type=float, default=60, help="fecha depois desse tempo sem uso (60)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if args.em_segundo_plano:
        try:
            url, started = ensure_running()
        except VagasError as exc:
            sys.exit(str(exc))
        print(f"Painel do mcp-vagas{'' if started else ' (já estava aberto)'}: {url}\n"
              "Ele fecha sozinho depois de uma hora sem uso; o atalho abre de novo.")
        if not args.sem_navegador:
            open_browser(url)
        return
    if url := running_url():
        print(f"O painel já está aberto: {url}")
        if not args.sem_navegador:
            open_browser(url)
        return
    server = make_server()
    state = remember(server)
    print(f"Painel do mcp-vagas: {server.url}\nDeixe esta janela aberta enquanto usa o painel (Ctrl+C fecha).",
          flush=True)
    if not args.sem_navegador:
        open_browser(server.url)
    threading.Thread(target=_close_when_idle, args=(server, args.minutos_sem_uso * 60), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.unlink(missing_ok=True)
        print("Painel fechado.")


if __name__ == "__main__":
    main()
