"""Tools MCP finas sobre o repo. Nunca escrever no stdout: no stdio ele é o canal do protocolo."""

import logging
import sqlite3
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
from vagas.resume_model import MasterResume
from vagas.resume_render import default_output_dir, render_resume
from vagas.resume_tailor import TailoredSelection
from vagas.resume_repo import ResumeStore, default_draft_path


def build_server(
    db_path: Path | str | None = None,
    draft_path: Path | str | None = None,
    resume_out: Path | str | None = None,
) -> MCPServer:
    server = MCPServer("vagas")

    @contextmanager
    def store(factory: Callable[[sqlite3.Connection], Any]) -> Iterator[Any]:
        try:
            with closing(connect(db_path)) as conn:
                yield factory(conn)
        except VagasError as exc:
            # Exceções comuns chegam ao cliente como mensagem genérica; ToolError preserva o texto.
            raise ToolError(str(exc)) from exc

    def repo():
        return store(Repo)

    def resumes():
        return store(lambda conn: ResumeStore(conn, draft_path or default_draft_path(db_path)))

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
        resume_id: int | None = None,
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
        resume_id: currículo personalizado enviado (create_tailored_resume); fica vinculado.
        """
        with repo() as r:
            return r.add_application(
                company=company, role=role, source=source, url=url, seniority=seniority,
                work_mode=work_mode, location=location,
                salary_expectation=salary_expectation, description=description,
                status=status, pending=pending, discard_reason=discard_reason, resume_id=resume_id,
            )

    @server.tool()
    def update_application(
        id: int,
        status: Status | None = None,
        note: str | None = None,
        pending: str | None = None,
        discard_reason: str | None = None,
        resume_id: int | None = None,
    ) -> dict[str, Any]:
        """Atualiza uma candidatura existente: etapa do processo, pendência e/ou anotação.

        - status: nova etapa. Qualquer transição entre status válidos é permitida, exceto
          para o mesmo status. Ao concluir uma candidatura pendente, usar status "aplicada"
          SOMENTE depois de submetida, e pending="" para limpar a pendência.
          "pendente_usuario" exige uma pendência; "descartada" exige discard_reason.
        - note: contexto livre (ex.: nome do recrutador, feedback). Fica no histórico.
        - pending: o que falta o usuário fazer, em qualquer etapa; "" limpa a pendência.
        - discard_reason: motivo, somente ao mudar o status para "descartada".
        - resume_id: vincula o currículo personalizado enviado nesta candidatura.

        Mudança de status e nota ficam registradas como eventos (ver get_history).
        Retorna a candidatura atualizada.
        """
        with repo() as r:
            return r.update_application(
                id, status=status, note=note, pending=pending, discard_reason=discard_reason,
                resume_id=resume_id,
            )

    @server.tool()
    def get_history(id: int) -> dict[str, Any]:
        """Retorna a candidatura e a linha do tempo completa, em ordem cronológica.

        Formato: {"application": {...}, "events": [{at, from_status, to_status, note}, ...]}.
        O primeiro evento é a criação (from_status nulo). Eventos com from_status igual a
        to_status são anotações sem mudança de etapa. "resumes" lista os currículos
        personalizados vinculados (id, label, pdf_path, created_at). Útil antes de uma entrevista.
        """
        with repo() as r:
            return r.get_history(id)

    @server.tool()
    def save_master_draft(resume: MasterResume, overwrite: bool = False) -> dict[str, Any]:
        """Grava o rascunho do currículo geral (em inglês) num arquivo YAML para o usuário revisar.

        Use para criar o currículo geral a partir do currículo atual do usuário ou para propor
        alterações nele. Nunca invente informação: tudo deve vir do currículo ou do usuário.
        IDs: slugs únicos (minúsculas, dígitos, hífens) que distinguem funções na mesma empresa,
        ex.: "exp-acme-analyst" e seus parágrafos "exp-acme-analyst-p1", "exp-acme-analyst-p2".
        Cada experiência tem "paragraphs" (a unidade de conteúdo), não bullets.

        Recusa sobrescrever um rascunho com edições do usuário ainda não aprovadas; overwrite=true
        só com a concordância dele. Retorna {"path"}: peça ao usuário para revisar e editar o arquivo.
        """
        with resumes() as s:
            return s.save_master_draft(resume, overwrite=overwrite)

    @server.tool()
    def approve_master() -> dict[str, Any]:
        """Promove o rascunho atual (inclusive edições feitas à mão) a currículo geral aprovado.

        Chamar SOMENTE quando o usuário disser explicitamente que revisou o rascunho e o aprova.
        Revalida o arquivo antes de aprovar. Aprovar conteúdo idêntico a uma versão existente não
        cria versão nova. Retorna {"created", "version_id", "content_hash"}.
        """
        with resumes() as s:
            return s.approve_master()

    @server.tool()
    def get_master_resume() -> dict[str, Any]:
        """Retorna o currículo geral aprovado mais recente: {"version_id", "approved_at", "resume"}.

        É a única fonte da verdade sobre experiência, formação, skills e idiomas do usuário,
        para escolher o que destacar numa vaga ou responder formulários.
        """
        with resumes() as s:
            return s.get_master_resume()

    @server.tool()
    def render_master_resume(label: str | None = None) -> dict[str, Any]:
        """Gera o PDF (em inglês, Typst, uma coluna, amigável a ATS) do currículo geral aprovado completo.

        O arquivo vai para a pasta de currículos configurada (VAGAS_RESUME_OUT), com nome
        "<Nome>_<Sobrenome>_Resume[_<label>].pdf"; nunca sobrescreve: acrescenta _2, _3...
        Retorna {"path", "pages", "warnings"}; warnings avisa se passar de 2 páginas.
        """
        with resumes() as s:
            master = s.get_master_resume()["resume"]
            return render_resume(master, resume_out or default_output_dir(), label=label)

    @server.tool()
    def create_tailored_resume(selection: TailoredSelection, application_id: int | None = None) -> dict[str, Any]:
        """Gera um currículo personalizado para uma vaga a partir do currículo geral aprovado.

        Escolha seções, itens e parágrafos (IDs de get_master_resume) e a ordem em que aparecem.
        Parágrafos longos podem ser reescritos como bullets objetivos, em inglês, destacando o que
        a vaga pede. Empresa, cargo, datas, local, formação, certificações e idiomas vêm sempre do
        currículo geral e não podem ser enviados.

        Antes de gerar, o MCP rejeita qualquer coisa que não esteja no currículo geral: ID
        inexistente, parágrafo de outro item, número que não está no parágrafo de origem (inclusive
        "3+ years"), tecnologia ou nome próprio que não aparece no currículo geral. Em caso de erro,
        corrija a seleção ou o texto; NUNCA tente contornar a validação nem exagerar
        responsabilidades (ex.: "contributed" não vira "led").

        application_id: candidatura à qual o currículo fica vinculado (opcional; também pode ser
        vinculado depois com add_application/update_application e resume_id).
        Retorna {"id", "path", "pages", "warnings"}; o PDF vai para VAGAS_RESUME_OUT.
        """
        with resumes() as s:
            return s.create_tailored_resume(selection, resume_out or default_output_dir(), application_id)

    @server.tool()
    def list_resumes(application_id: int | None = None) -> dict[str, Any]:
        """Lista os currículos personalizados gerados, mais recentes primeiro: {"resumes": [...]}.
        Com application_id, só os vinculados àquela candidatura."""
        with resumes() as s:
            return {"resumes": s.list_resumes(application_id)}

    @server.tool()
    def get_resume(id: int) -> dict[str, Any]:
        """Retorna um currículo personalizado: seleção enviada, conteúdo final ("resolved"),
        versão do currículo geral de origem, caminho do PDF e páginas."""
        with resumes() as s:
            return s.get_resume(id)

    return server


server = build_server()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    server.run("stdio")


if __name__ == "__main__":
    main()
