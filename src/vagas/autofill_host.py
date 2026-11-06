"""Host de native messaging da extensão do Chrome (preenchimento de documentos do cofre).

O Chrome, no Windows, chama o .bat gerado pelo instalador, que roda `python -m vagas.autofill_host`
no WSL pelo wsl.exe. Mensagens: 4 bytes de tamanho (little-endian) + JSON, em stdin e stdout.
Ao contrário do servidor MCP, aqui o stdout é o canal da extensão; logs vão para o stderr.
A decisão (domínio, empresa, confirmação, valores) fica em `vagas.autofill`.
"""

import json
import logging
import struct
import sys
from typing import Any, BinaryIO

from vagas import config
from vagas.autofill import Applications, Approvals, Autofill, default_approvals_path, default_log_path
from vagas.db import default_db_path
from vagas.sensitive import DpapiBackend, Vault, default_vault_path

log = logging.getLogger("vagas.autofill_host")
MAX_MESSAGE = 1024 * 1024  # mensagens da extensão para o host têm até 4 GB; aqui, uma página pequena basta


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Próxima mensagem, ou None no fim da entrada. ValueError se o JSON for inválido."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    size = struct.unpack("<I", header)[0]
    if size > MAX_MESSAGE:
        raise ValueError(f"mensagem grande demais ({size} bytes)")
    return json.loads(stream.read(size).decode("utf-8"))


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    data = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()


def serve(incoming: BinaryIO, outgoing: BinaryIO, autofill: Autofill) -> None:
    while True:
        try:
            message = read_message(incoming)
        except ValueError as exc:
            write_message(outgoing, {"status": "error", "message": f"Mensagem inválida: {exc}"})
            continue
        if message is None:
            return
        try:
            response = autofill.handle(message)
        except Exception as exc:  # a extensão mostra o erro; o processo segue para a próxima mensagem
            log.exception("falha ao atender a extensão")
            response = {"status": "error", "message": str(exc)}
        write_message(outgoing, response)


def build_autofill() -> Autofill:
    db_path = default_db_path()

    def extra_domains() -> list[str]:
        value = config.resolve("autofill_domains", db_path)[0]
        return config.split_domains(value) if value else []

    def platforms() -> list[str]:
        value = config.resolve("autofill_platforms", db_path)[0]
        return config.split_domains(value) if value else []

    applications = Applications(db_path)
    return Autofill(Vault(default_vault_path(db_path), DpapiBackend()), Approvals(default_approvals_path(db_path)),
                    log_path=default_log_path(db_path), open_sites=applications.sites, extra_domains=extra_domains,
                    resumes=applications.with_resumes, platforms=platforms)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    serve(sys.stdin.buffer, sys.stdout.buffer, build_autofill())


if __name__ == "__main__":
    main()
