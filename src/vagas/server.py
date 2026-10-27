"""Tools MCP finas sobre o repo. Nunca escrever no stdout: no stdio ele é o canal do protocolo."""

import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from vagas.db import connect
from vagas.models import Source, WorkMode
from vagas.repo import Repo, VagasError


def build_server(db_path: Path | str | None = None) -> MCPServer:
    server = MCPServer("vagas")

    @contextmanager
    def repo() -> Iterator[Repo]:
        try:
            with closing(connect(db_path)) as conn:
                yield Repo(conn)
        except VagasError as exc:
            # Exceções comuns chegam ao cliente como mensagem genérica; ToolError preserva o texto.
            raise ToolError(str(exc)) from exc

    @server.tool()
    def find_application(url: str | None = None) -> dict[str, Any]:
        """Procura candidaturas já registradas para uma vaga.

        SEMPRE chamar antes de iniciar qualquer candidatura, antes de abrir o formulário.
        Se houver registro, não iniciar uma nova candidatura: informar o status atual ao usuário.

        A URL é comparada em forma normalizada (sem fragmento e sem parâmetros utm_*).
        Retorna {"matches": [candidaturas]}; lista vazia quando a vaga não foi registrada.
        """
        with repo() as r:
            return {"matches": r.find_application(url=url)}

    @server.tool()
    def add_application(
        company: str,
        role: str,
        source: Source,
        url: str | None = None,
        seniority: str | None = None,
        work_mode: WorkMode | None = None,
        location: str | None = None,
        salary_expectation: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Registra uma candidatura submetida, com status "aplicada".

        Chamar somente depois que a candidatura foi de fato enviada.
        Se a URL já estiver registrada, NÃO cria outro registro: retorna
        {"created": false, "application": <registro existente>} sem erro.
        Caso contrário retorna {"created": true, "application": <novo registro>}.

        description: texto da vaga (requisitos, responsabilidades), para consulta futura.
        salary_expectation: pretensão informada no formulário, em texto livre.
        """
        with repo() as r:
            return r.add_application(
                company=company, role=role, source=source, url=url, seniority=seniority,
                work_mode=work_mode, location=location,
                salary_expectation=salary_expectation, description=description,
            )

    return server


server = build_server()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    server.run("stdio")


if __name__ == "__main__":
    main()
