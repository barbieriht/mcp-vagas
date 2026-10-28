"""Tools MCP finas sobre o repo. Nunca escrever no stdout: no stdio ele é o canal do protocolo."""

import logging
import sqlite3
import sys
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field
from mcp.server.mcpserver.exceptions import ToolError

from vagas.db import connect
from vagas.models import (
    Contract, Currency, InitialStatus, LinkedInSection, ResumeSourceKind, RoleKey, SalaryMode, Seniority,
    Source, Status, WorkMode,
)
from vagas.repo import Repo, VagasError
from vagas.resume_model import MasterResume
from vagas.resume_render import default_output_dir, render_resume
from vagas.resume_tailor import TailoredSelection
from vagas.export import default_export_dir, export_csv as write_csv
from vagas.job_search import JobSearchStore
from vagas.linkedin_import import LinkedInImporter
from vagas.salary import SalaryPoint, SalaryStore
from vagas.resume_repo import ResumeStore, default_draft_path


class MatchTerms(BaseModel):
    """Termos da vaga presentes e ausentes no currículo, como devolvidos por score_job_match."""

    model_config = ConfigDict(extra="forbid")
    matched: list[str]
    missing: list[str]


def build_server(
    db_path: Path | str | None = None,
    draft_path: Path | str | None = None,
    resume_out: Path | str | None = None,
    linkedin_reader: Any = None,
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

    def salaries():
        return store(SalaryStore)

    def job_searches():
        return store(JobSearchStore)

    @server.tool()
    def find_application(url: str | None = None, company: str | None = None) -> dict[str, Any]:
        """Procura candidaturas já registradas para uma vaga, por URL e/ou por empresa.

        SEMPRE chamar antes de iniciar qualquer candidatura, antes de abrir o formulário.
        Interpretação do resultado:
        - nenhum registro: seguir com a triagem e a candidatura;
        - registro com status "pendente_usuario": retomar a candidatura a partir do que
          está descrito em "pending" (não criar outro registro);
        - registro com status "a_aplicar": vaga já encontrada e triada, na lista de trabalho:
          seguir com a candidatura e, ao final, atualizar o registro com update_application
          (não criar outro registro);
        - registro com qualquer outro status (inclusive "descartada", com "discard_reason"):
          parar e informar o status atual ao usuário.

        Passe os dois quando souber. A URL é comparada em forma normalizada: no LinkedIn, Gupy,
        Indeed e Glassdoor, pelo identificador da vaga (links de busca, coleções, slugs e
        subdomínios de país caem na mesma vaga); nos demais sites, sem fragmento nem parâmetros
        de rastreamento. A empresa ignora maiúsculas, acentos, pontuação e sufixos societários
        ("Itaú Unibanco S.A." = "itau unibanco") e devolve TODAS as vagas daquela empresa: decida
        se alguma é a mesma vaga publicada em outra plataforma (mesmo cargo e senioridade) e, na
        dúvida, pergunte ao usuário.
        Retorna {"matches": [candidaturas]}, mais recentes primeiro; lista vazia se não houver.
        """
        with repo() as r:
            return {"matches": r.find_application(url=url, company=company)}

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
        search_id: int | None = None,
        match_score: Annotated[int, Field(ge=0, le=100)] | None = None,
        match_terms: MatchTerms | None = None,
    ) -> dict[str, Any]:
        """Registra uma vaga: encontrada e triada, candidatura enviada, incompleta ou descartada.

        status:
        - "a_aplicar": vaga encontrada numa busca e aprovada na triagem, aguardando candidatura
          (lista de trabalho). NUNCA registre como "aplicada" uma vaga só encontrada;
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
        search_id: busca de origem (save_job_search), para vagas encontradas em buscas.
        match_score / match_terms: aderência ao currículo, como devolvida por score_job_match.
        """
        with repo() as r:
            return r.add_application(
                company=company, role=role, source=source, url=url, seniority=seniority,
                work_mode=work_mode, location=location,
                salary_expectation=salary_expectation, description=description,
                status=status, pending=pending, discard_reason=discard_reason, resume_id=resume_id,
                search_id=search_id, match_score=match_score,
                match_terms=match_terms.model_dump() if match_terms is not None else None,
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
    def list_applications(
        status: Status | None = None,
        only_pending: bool = False,
        source: Source | None = None,
        since: str | None = None,
        stale_days: int | None = None,
    ) -> dict[str, Any]:
        """Lista candidaturas, mais recentes primeiro; os filtros se combinam.

        - status: uma etapa (ex.: "descartada", "tecnica"). Com "a_aplicar" (lista de trabalho), a
          ordem é pela aderência ao currículo (match_score, maior primeiro; sem nota por último);
        - only_pending: só as que têm pendência do usuário (campo pending);
        - source: plataforma;
        - since: criadas a partir desta data ISO (ex.: "2026-10-01");
        - stale_days: só "aplicada" sem nenhum evento há mais de N dias (candidaturas sem resposta).
        Cada item traz last_event_at (data do último evento). Retorna {"applications", "count"}.
        """
        with repo() as r:
            return r.list_applications(
                status=status, only_pending=only_pending, source=source, since=since, stale_days=stale_days,
            )

    @server.tool()
    def export_csv() -> dict[str, Any]:
        """Exporta todas as candidaturas para um arquivo CSV novo, para abrir numa planilha.

        Todas as colunas, uma linha por candidatura, mais recentes primeiro; separador ";" e UTF-8
        (abre direto no Excel em português e no Google Sheets). O arquivo vai para a pasta de
        exportação (VAGAS_EXPORT_DIR, padrão "exports" ao lado do banco) com data e hora no nome;
        nunca sobrescreve. Retorna {"path", "rows"}.
        """
        with repo() as r:
            return write_csv(r, default_export_dir(db_path))

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
    def extract_resume_text(pdf_path: str) -> dict[str, Any]:
        """Extrai o texto do PDF do currículo do usuário (aceita caminho do Windows ou do WSL).

        Primeiro passo para criar o currículo geral: leia o texto devolvido (e, se puder, o próprio
        PDF), monte a estrutura e chame save_master_draft. O texto fica guardado como referência:
        save_master_draft passa a devolver "review", a lista do que não foi encontrado no PDF.
        Retorna {"path", "page_count", "pages"}.
        """
        with resumes() as s:
            return s.extract_resume_text(pdf_path)

    @server.tool()
    def import_linkedin_profile(url: str) -> dict[str, Any]:
        """Lê o perfil do LinkedIn do PRÓPRIO usuário por código (sem a LLM transcrever a página).

        Chamar SOMENTE quando o usuário pedir para montar ou atualizar o currículo geral; nunca como
        efeito colateral de outros fluxos (busca, triagem, candidatura). A tool não altera o rascunho
        nem o currículo aprovado: devolve os itens e registra o texto como fonte (kind linkedin).

        Usa a sessão salva pelo comando de login (`python -m vagas.linkedin login`, feito pelo usuário).
        Lê a página do perfil (headline e About) e as páginas de Experience, Education, Licenses &
        certifications, Volunteering, Languages e Skills por completo (rola e carrega todos os itens,
        expande descrições cortadas) e devolve os itens já no formato do currículo geral:
        cargos agrupados por empresa viram itens separados, qualificador do cargo vai para context,
        Remote/Hybrid/On-site para work_mode, formação em andamento com end "Present" e previsão em
        notes, certificações com mês de emissão, ID e link real da credencial.
        Retorna {"items": {headline, summary, experience, education, certifications, volunteering,
        languages, skills}, "extras" (anexos por experiência), "completeness", "warnings", "source_id"}.
        Leva cerca de 3 minutos.
        Se der erro (sessão expirada, verificação de segurança, intervalo mínimo entre leituras ou
        Playwright ausente), informe o usuário e use a leitura pelo navegador como plano B.
        """
        def reader():
            if linkedin_reader is not None:
                return linkedin_reader
            from vagas.linkedin import LinkedInReader
            return LinkedInReader()

        with resumes() as s:
            return LinkedInImporter(s, reader()).import_profile(url)

    @server.tool()
    def save_resume_source(
        kind: ResumeSourceKind,
        url: str,
        sections: dict[LinkedInSection, str] | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        """Registra uma fonte do currículo geral: o perfil do LinkedIn do usuário ou o texto de um PDF.

        kind="pdf": use quando o PDF não está acessível por caminho local (ex.: anexado no chat) e
        você já leu o conteúdo: passe o texto completo em "text" e o nome do arquivo em "url".
        Retorna {"source_id", "chars"}. Com caminho local, prefira extract_resume_text.

        kind="linkedin": texto por seção em "sections".

        Leia SOMENTE o perfil do próprio usuário, logado com a conta dele, no ritmo de uma pessoa.
        Para cada seção (about, experience, education, certifications, volunteering), abra a página de
        detalhes ("Show all", ex.: /details/certifications/), role até o fim até a lista parar de
        carregar e confira a contagem de itens que a página mostra; então copie o texto da seção
        inteira. Passe url = endereço do perfil. Depois, monte o rascunho com save_master_draft: o
        relatório de revisão passa a conferir o rascunho contra o PDF e o LinkedIn juntos.
        Retorna {"source_id", "sections": {seção: nº de caracteres}}.
        """
        with resumes() as s:
            return s.save_resume_source(kind, url, sections=sections, text=text)

    @server.tool()
    def save_master_draft(resume: MasterResume, overwrite: bool = False) -> dict[str, Any]:
        """Grava o rascunho do currículo geral (em inglês) num arquivo YAML para o usuário revisar.

        Use para criar o currículo geral a partir do currículo atual do usuário ou para propor
        alterações nele. Nunca invente informação: tudo deve vir do currículo ou do usuário.
        IDs: slugs únicos (minúsculas, dígitos, hífens) que distinguem funções na mesma empresa,
        ex.: "exp-acme-analyst" e seus parágrafos "exp-acme-analyst-p1", "exp-acme-analyst-p2".
        Cada experiência tem "paragraphs" (a unidade de conteúdo), não bullets.

        Recusa sobrescrever um rascunho com edições do usuário ainda não aprovadas; overwrite=true
        só com a concordância dele. Retorna {"path", "sources", "review"}: peça ao usuário para
        revisar e editar o arquivo. Com fontes registradas (PDF via extract_resume_text, LinkedIn via
        save_resume_source), "review" lista números, datas, nomes e termos do rascunho que não estão
        em NENHUMA fonte: mostre-os ao usuário e corrija o que for erro de extração; peça que ele os
        confira antes de aprovar.
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
    def score_job_match(description: str) -> dict[str, Any]:
        """Aderência de uma vaga ao currículo geral aprovado, a partir da descrição da vaga.

        Extrai os termos técnicos da descrição (tecnologias, siglas, nomes próprios) e separa os
        que aparecem no currículo geral ("matched") dos que não aparecem ("missing"). "score" é a
        proporção de presentes, de 0 a 100 (null se a descrição não tiver termos técnicos).
        A nota é INDICATIVA: nomes de cidades, empresas ou palavras capitalizadas podem aparecer
        como ausentes, e termos ausentes no início de frase ou de item de lista podem não ser
        detectados (a nota tende a sair um pouco otimista). Use-a para justificar a triagem e para escolher o que destacar no
        currículo personalizado; a decisão de aplicar continua sendo da triagem completa.
        """
        with resumes() as s:
            return s.score_job_match(description)

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

    @server.tool()
    def find_salary_estimate(
        role_key: RoleKey, seniority: Seniority, currency: Currency, company: str | None = None,
    ) -> dict[str, Any]:
        """Consulta o cache de salários para família de cargo + senioridade + moeda.

        SEMPRE consultar antes de pesquisar salários na web. Pesquise e registre
        (save_salary_estimate) só o que não estiver fresco: fresh_company=false (com company
        informada) e/ou fresh_market=false. Dados ficam frescos por 90 dias (configurável).
        role_key agrupa grafias ("Cientista de Dados" e "Data Scientist" = data_scientist).

        Retorna {"company", "market", "fresh_company", "fresh_market", "points"}. "company" e
        "market" são resumos dos dados frescos (mediana mensal, min, max, nº de fontes,
        confidence baixa/media/alta, nothing_found) ou null. Valores mensais na base de cada
        ponto (CLT ou PJ); a conversão de regime é feita na avaliação.
        """
        with salaries() as s:
            return s.find_salary_estimate(role_key, seniority, currency, company=company)

    @server.tool()
    def save_salary_estimate(
        role_key: RoleKey,
        seniority: Seniority,
        currency: Currency,
        points: list[SalaryPoint],
        company: str | None = None,
        note: str | None = None,
        application_id: int | None = None,
    ) -> dict[str, Any]:
        """Registra o resultado de uma pesquisa de salários na web.

        Um ponto por dado encontrado, com fonte e URL, período (hora/mes/ano), regime
        (clt/pj/desconhecido) e ao menos um entre min_value, avg_value e max_value, exatamente
        como a fonte informa (a conversão para mensal é automática). NUNCA invente valores nem
        estime por conta própria: se não encontrou nada, registre points=[] (com note dizendo onde
        procurou), o que evita repetir a pesquisa antes da validade.
        Sem company: dados de mercado para o cargo e senioridade. Moedas nunca são convertidas.
        Faixa salarial publicada na própria vaga: registre com source "vaga" e application_id da
        candidatura (e company); ela passa a ter prioridade na avaliação dessa vaga e não expira.
        Retorna {"search_id", "points"}.
        """
        with salaries() as s:
            return s.save_salary_estimate(role_key, seniority, currency, points, company=company, note=note,
                                          application_id=application_id)

    @server.tool()
    def evaluate_salary(
        role_key: RoleKey,
        seniority: Seniority,
        currency: Currency,
        contract: Contract,
        my_min: float,
        my_max: float | None = None,
        mode: SalaryMode = "minimo",
        pj_multiplier: float | None = None,
        company: str | None = None,
        application_id: int | None = None,
    ) -> dict[str, Any]:
        """Triagem salarial de uma vaga e valor de pretensão a informar no formulário.

        Use a política do perfil.md: my_min/my_max = faixa MENSAL em CLT da modalidade da vaga,
        mode ("minimo": aplicar se a mediana >= mínimo; "faixa": só se estiver dentro da faixa) e
        pj_multiplier. contract = regime da vaga (desconhecido é tratado como CLT); para vaga PJ a
        faixa é multiplicada e o valor sai em PJ. Base: faixa publicada na vaga (application_id),
        senão dados frescos da empresa, senão de mercado. Com application_id, a avaliação fica
        gravada na candidatura (salary_evaluation, visível em get_history).

        decision: "aplicar" (use value_to_inform no campo de pretensão), "nao_aplicar" (registre a
        vaga como descartada usando reason como motivo) ou "pesquisar" (pesquise salários e chame
        save_salary_estimate antes). needs_research=true sugere pesquisar também a empresa.
        Retorna {decision, value_to_inform, basis, contract, median, range, sources, confidence,
        needs_research, reason}.
        """
        with salaries() as s:
            return s.evaluate_salary(
                role_key, seniority, currency, contract, my_min, my_max=my_max, mode=mode,
                pj_multiplier=pj_multiplier, company=company, application_id=application_id,
            )

    @server.tool()
    def find_job_search(query: str, source: Source, location: str | None = None) -> dict[str, Any]:
        """Consulta se uma busca de vagas equivalente já foi feita e quando.

        Chamar ANTES de executar cada busca num site. Se "recent" for true (feita há menos de
        "min_hours", padrão 24h), não repita a busca: vagas novas ainda não apareceram. A consulta
        e o local são comparados sem diferenciar maiúsculas, acentos e espaços.
        Retorna {"search": {id, query, source, location, filters, results_count, searched_at,
        note} | null, "recent", "hours_since", "min_hours"}.
        """
        with job_searches() as s:
            return s.find_job_search(query, source, location=location)

    @server.tool()
    def save_job_search(
        query: str,
        source: Source,
        results_count: int,
        location: str | None = None,
        filters: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Registra uma busca de vagas executada num site, inclusive quando não houve resultados.

        query: termos exatamente como buscados; source: site; location: local filtrado (vazio se
        nenhum); filters: outros filtros usados (ex.: {"posted": "24h", "remote": true});
        results_count: quantas vagas a busca mostrou. Retorna {"search_id"}, a ser passado ao
        registrar as vagas encontradas.
        """
        with job_searches() as s:
            return s.save_job_search(query, source, results_count, location=location, filters=filters, note=note)

    return server


server = build_server()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    server.run("stdio")


if __name__ == "__main__":
    main()
