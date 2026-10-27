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
from vagas.models import InitialStatus, Source, Status, WorkMode
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
        Interpretação do resultado:
        - nenhum registro: seguir com a triagem e a candidatura;
        - registro com status "pendente_usuario": retomar a candidatura a partir do que
          está descrito em "pending" (não criar outro registro);
        - registro com qualquer outro status (inclusive "descartada", com "discard_reason"):
          parar e informar o status atual ao usuário.

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
        status: InitialStatus = "aplicada",
        pending: str | None = None,
        discard_reason: str | None = None,
    ) -> dict[str, Any]:
        """Registra uma vaga: candidatura enviada, incompleta ou descartada na triagem.

        status:
        - "aplicada": SOMENTE se a candidatura foi de fato submetida;
        - "pendente_usuario": candidatura incompleta; "pending" é obrigatório e descreve
          o que falta o usuário fazer (ex.: "CPF", "criar conta", "responder pergunta X");
        - "descartada": vaga reprovada na triagem; "discard_reason" é obrigatório.
        "pending" também pode acompanhar "aplicada" (ex.: "teste técnico até sexta").

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
                status=status, pending=pending, discard_reason=discard_reason,
            )

    @server.tool()
    def update_application(
        id: int,
        status: Status | None = None,
        note: str | None = None,
        pending: str | None = None,
        discard_reason: str | None = None,
    ) -> dict[str, Any]:
        """Atualiza uma candidatura existente: etapa do processo, pendência e/ou anotação.

        - status: nova etapa. Qualquer transição entre status válidos é permitida, exceto
          para o mesmo status. Ao concluir uma candidatura pendente, usar status "aplicada"
          SOMENTE depois de submetida, e pending="" para limpar a pendência.
          "pendente_usuario" exige uma pendência; "descartada" exige discard_reason.
        - note: contexto livre (ex.: nome do recrutador, feedback). Fica no histórico.
        - pending: o que falta o usuário fazer, em qualquer etapa; "" limpa a pendência.
        - discard_reason: motivo, somente ao mudar o status para "descartada".

        Mudança de status e nota ficam registradas como eventos (ver get_history).
        Retorna a candidatura atualizada.
        """
        with repo() as r:
            return r.update_application(
                id, status=status, note=note, pending=pending, discard_reason=discard_reason,
            )

    @server.tool()
    def get_history(id: int) -> dict[str, Any]:
        """Retorna a candidatura e a linha do tempo completa, em ordem cronológica.

        Formato: {"application": {...}, "events": [{at, from_status, to_status, note}, ...]}.
        O primeiro evento é a criação (from_status nulo). Eventos com from_status igual a
        to_status são anotações sem mudança de etapa. Útil antes de uma entrevista.
        """
        with repo() as r:
            return r.get_history(id)

    return server


server = build_server()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    server.run("stdio")


if __name__ == "__main__":
    main()
