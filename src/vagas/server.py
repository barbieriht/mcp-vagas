"""Tools MCP finas sobre o repo. Nunca escrever no stdout: no stdio ele é o canal do protocolo."""

import logging
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field
from mcp.server.mcpserver.exceptions import ToolError

from vagas import config as paths_config
from vagas.db import connect, default_db_path
from vagas.models import (
    Contract, Currency, InitialStatus, LinkedInSection, ResumeSourceKind, RoleKey, SalaryMode, Seniority,
    Source, Status, WorkMode,
)
from vagas.repo import Repo, VagasError
from vagas.resume_model import MasterResume
from vagas.resume_render import default_output_dir, render_resume
from vagas.resume_tailor import TailoredSelection
from vagas.export import default_export_dir, export_csv as write_csv
from vagas.job_posting import JobPostingError, http_fetch, read_job_posting as fetch_job
from vagas.job_board import JobBoard
from vagas.job_search import JobSearchStore
from vagas.linkedin_import import LinkedInImporter
from vagas.salary import SalaryPoint, SalaryStore
from vagas.profile_fields import ProfileFiles, default_skill_dir
from vagas.search_run import SearchRunStore
from vagas.sensitive import DpapiBackend, SensitiveAccess, Vault, default_vault_path
from vagas.salary_policy import default_policy_path
from vagas.triage import Triage, default_criteria_path
from vagas.work_list import build_work_list
from vagas.resume_repo import ResumeStore, default_draft_path


class MatchTerms(BaseModel):
    """Termos da vaga presentes e ausentes no currículo, como devolvidos por score_job_match."""

    model_config = ConfigDict(extra="forbid")
    matched: list[str]
    missing: list[str]


_VALUE_KEYS = ("default", "enum", "const", "examples")


def _without_titles(node: Any, in_properties: bool = False) -> Any:
    """Tira o `title` que o pydantic gera em cada campo ("Work Mode"): repete o nome do campo e custa tokens.
    Campos chamados `title` (chaves de `properties`) e valores de default/enum ficam como estão."""
    if isinstance(node, dict):
        return {key: value if key in _VALUE_KEYS else _without_titles(value, key in ("properties", "$defs"))
                for key, value in node.items() if not (key == "title" and isinstance(value, str) and not in_properties)}
    if isinstance(node, list):
        return [_without_titles(item) for item in node]
    return node


def build_server(
    db_path: Path | str | None = None,
    draft_path: Path | str | None = None,
    resume_out: Path | str | None = None,
    linkedin_reader: Any = None,
    job_fetcher: Any = None,
    job_search_fetcher: Any = None,
    vault: Any = None,
    search_launcher: Callable[[int], int] | None = None,
) -> MCPServer:
    server = MCPServer("vagas", instructions=(
        "No primeiro uso, chame get_config: se needs_setup trouxer chaves, pergunte ao usuário onde guardar "
        "cada coisa (pasta dos currículos em PDF, pasta dos CSVs, arquivo do currículo geral), sugerindo "
        "uma das suggestions (ou o default) e grave a resposta com set_config. Não escolha sozinho a pasta "
        "dos currículos. Ao citar uma vaga ao usuário (resumos, listas, tabelas, pendências), escreva o nome "
        "dela como link Markdown para a página da vaga, no formato [Cargo — Empresa](url), usando o campo url "
        "que as tools retornam; se a vaga não tiver url, escreva o nome sem link. Não mostre a URL crua ao lado."))

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

    def salary_rule() -> str:
        return paths_config.resolve("salary_rule", db_path)[0]

    def salaries():
        return store(lambda conn: SalaryStore(conn, policy_path=default_policy_path(db_path), rule=salary_rule()))

    def job_searches():
        return store(JobSearchStore)

    def boards():
        return store(lambda conn: JobBoard(
            conn, fetcher=job_search_fetcher or http_fetch, criteria_path=default_criteria_path(db_path),
            draft_path=draft_path or default_draft_path(db_path)))

    def launch_search_run(run_id: int) -> int:
        """Dispara a busca em lote num processo separado (sem herdar o stdout do protocolo); devolve o PID."""
        db = Path(db_path) if db_path is not None else default_db_path()
        log_file = open(db.parent / "search_runs.log", "a", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "-m", "vagas.search_run", "run", "--run-id", str(run_id)],
            env={**os.environ, "VAGAS_DB": str(db)}, stdin=subprocess.DEVNULL, stdout=log_file, stderr=log_file,
            start_new_session=True,
        )
        log_file.close()
        return process.pid

    def triages():
        return store(lambda conn: Triage(
            conn, fetcher=job_fetcher or http_fetch, criteria_path=default_criteria_path(db_path),
            policy_path=default_policy_path(db_path), draft_path=draft_path or default_draft_path(db_path),
            salary_rule=salary_rule()))

    @server.tool()
    def get_config() -> dict[str, Any]:
        """Mostra onde o MCP guarda os arquivos de cada tarefa e o que ainda falta configurar.

        Chame no PRIMEIRO USO (e sempre que uma tool reclamar de pasta não configurada), antes de gerar
        currículo ou exportar. Retorna {config_file, settings, needs_setup}. Em settings, cada chave
        (resume_out = pasta dos PDFs de currículo, export_dir = pasta dos CSVs, master_resume = arquivo
        YAML do currículo geral, login_method = entrar nos sites de vagas por "linkedin" ou "google",
        login_email = conta Google usada quando login_method é "google", max_open_tabs = limite de abas de
        candidatura abertas esperando o usuário, padrão 12, nunca perguntado; salary_rule = regra da
        pretensão salarial, padrão "teto", perguntada só depois da primeira busca de vagas) traz {value, source
        (env/config/default/unset), description, kind, default, suggestions, choices, env}.
        needs_setup lista as chaves que o usuário nunca definiu: pergunte uma por vez (para pastas,
        ofereça a sugestão mais adequada: suggestions, ou o default quando houver; para login_method,
        as choices; login_email só aparece quando o login é por Google) e grave com set_config.
        """
        try:
            return paths_config.describe(db_path)
        except VagasError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def set_config(key: str, value: str | None = None) -> dict[str, Any]:
        """Grava uma configuração no config.toml (para pastas, cria a pasta e confere que dá para escrever).

        key: resume_out, export_dir ou master_resume (value: caminho absoluto, aceita C:\\Users\\...);
        login_method (value: "linkedin" ou "google"/"gmail"); login_email (value: e-mail da conta Google);
        max_open_tabs (value: número de 1 a 30); salary_rule (value: teto, meio_termo, percentil_25 ou
        ponto_baixo). Ao gravar salary_rule, as vagas a_aplicar e pendente_usuario já avaliadas são
        reavaliadas com a regra nova: o retorno traz "reevaluated" ({reevaluated, changed, errors}),
        para mostrar ao usuário a tabela ajustada (before -> after de cada vaga).
        Sem value, confirma o padrão da chave (só export_dir e master_resume têm padrão). Use depois de
        perguntar ao usuário, nunca escolha sozinho a pasta dos currículos. Retorna {key, value, source,
        config_file, warnings}; se source for "env", uma variável de ambiente do servidor sobrepõe o valor.
        """
        try:
            saved = paths_config.set_value(key, value, db_path)
        except VagasError as exc:
            raise ToolError(str(exc)) from exc
        if key == "salary_rule":
            with salaries() as s:
                saved["reevaluated"] = s.reevaluate_applications()
        return saved

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
        contract: Contract = "desconhecido",
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
        contract: regime da vaga (clt, pj ou desconhecido), como lido em read_job_posting.
        """
        with repo() as r:
            return r.add_application(
                company=company, role=role, source=source, url=url, seniority=seniority,
                work_mode=work_mode, location=location,
                salary_expectation=salary_expectation, description=description,
                status=status, pending=pending, discard_reason=discard_reason, resume_id=resume_id,
                search_id=search_id, match_score=match_score,
                match_terms=match_terms.model_dump() if match_terms is not None else None,
                contract=contract,
            )

    @server.tool()
    def update_application(
        id: int,
        status: Status | None = None,
        note: str | None = None,
        pending: str | None = None,
        discard_reason: str | None = None,
        resume_id: int | None = None,
        contract: Contract | None = None,
        salary_expectation: str | None = None,
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
        - contract: corrige o regime da vaga (clt, pj ou desconhecido).
        - salary_expectation: pretensão informada no formulário, como foi digitada (ex.: "R$ 15.500").
          Registre ao enviar a candidatura; fica separada da pretensão calculada (salary_ask).

        Mudança de status e nota ficam registradas como eventos (ver get_history).
        Retorna a candidatura atualizada.
        """
        with repo() as r:
            return r.update_application(
                id, status=status, note=note, pending=pending, discard_reason=discard_reason,
                resume_id=resume_id, contract=contract, salary_expectation=salary_expectation,
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
    def get_sensitive_field(field: str, application_id: int, form_url: str) -> dict[str, Any]:
        """Entrega um dado do cofre (CPF, RG...) para preencher um formulário de candidatura.

        SÓ chame depois de o usuário confirmar explicitamente, nesta conversa, este uso: qual dado, em
        qual vaga e empresa e em qual domínio ("vou preencher o seu CPF na vaga X da empresa Y,
        domínio Z"). Sem essa confirmação, não chame. Digite o valor apenas no campo do formulário:
        nunca o escreva na conversa, em resumos, notas ou arquivos.
        field: cpf, rg, rg_orgao_emissor, cnh, pis, ctps, titulo_eleitor, passaporte ou nome_mae.
        form_url: endereço https da página do formulário aberta agora. Condições: candidatura em
        a_aplicar ou pendente_usuario, e domínio do formulário igual ao da vaga, à Gupy ou ao LinkedIn.
        O uso fica registrado no histórico da candidatura, sem o valor. Em qualquer recusa (domínio,
        status, campo fora do cofre), não preencha: registre a candidatura como pendente_usuario com
        o motivo. Retorna {field, label, value, domain}.
        """
        def access(conn):
            return SensitiveAccess(Repo(conn), vault or Vault(default_vault_path(db_path), DpapiBackend()))

        with store(access) as a:
            return a.get_sensitive_field(field, application_id, form_url)

    @server.tool()
    def get_profile() -> dict[str, Any]:
        """Perfil do usuário para formulários, estruturado (perfil.md da Skill): use no lugar de ler o arquivo.

        Retorna {sections: [{name, fields: [{label, value, status, notes, vault_field?}]}], to_fill,
        vault_missing}. status: "ok" (use o value), "preencher" (ainda sem resposta: trate como
        bloqueio e pergunte ao usuário), "manual" (dado sensível: o usuário digita), "cofre" (preencha
        com get_sensitive_field, após a confirmação do usuário; o value nunca é o dado) ou "cofre_vazio"
        (marcado como no cofre, mas não cadastrado: o usuário cadastra com python -m vagas.sensitive
        set <vault_field>). notes: orientações do campo (ex.: como escolher em escala fixa).
        """
        try:
            fields = (vault or Vault(default_vault_path(db_path), DpapiBackend())).list()
            return ProfileFiles(default_skill_dir(db_path)).get_profile(vault_fields=fields)
        except VagasError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def add_profile_field(label: str, section: str | None = None, value: str | None = None,
                          sensitive: bool = False) -> dict[str, Any]:
        """Acrescenta um campo de formulário ao perfil (perfil.md e perfil.example.md da Skill).

        Use quando um formulário pedir um dado que não está no perfil nem no currículo geral, em vez
        de editar os arquivos à mão. label: rótulo como o formulário pede. section: seção existente do
        perfil (ex.: "Contato e identificação", "Respostas padrão"); sem ela, "Outros campos de
        formulário". value: a resposta do usuário; sem ela, o perfil recebe <PREENCHER> e o exemplo
        <...>. Campo já existente não é recriado; com value, um <PREENCHER> existente recebe a
        resposta (valor já preenchido não é trocado). Dados sensíveis (CPF, RG, CNH, passaporte,
        senhas, dados bancários, ou sensitive=true) nunca guardam valor e ficam como
        "informar manualmente"; enviar value para eles é erro.
        A pasta da Skill vem de VAGAS_SKILL_DIR (ou do symlink da política salarial criado pelo
        instalador). No Claude Desktop, que usa uma cópia da Skill enviada em zip, reenvie o zip
        depois. Retorna {created: {perfil, example}, updated, section, line}.
        """
        try:
            files = ProfileFiles(default_skill_dir(db_path))
            return files.add_profile_field(label, section=section, value=value, sensitive=sensitive)
        except VagasError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def diff_master(items: dict[str, Any]) -> dict[str, Any]:
        """Compara itens das fontes com o currículo geral aprovado, para a ATUALIZAÇÃO do currículo geral.

        items: seções no formato do currículo geral (headline, summary, experience, education,
        certifications, volunteering, languages, skills), como o "items" de import_linkedin_profile
        ou itens montados a partir do PDF. Casa cada item por chave natural, tolerando grafias e
        aliases de título: experience = empresa + cargo + início; certifications = credential_id
        (senão nome + emissor); education = instituição + grau; volunteering = organização + papel;
        languages = nome; skills = termo.
        Retorna {new: {seção: itens novos, com IDs únicos; skills: {grupo: termos}}, changed:
        [{section, id, fields: {campo: {old, new}}}], missing: {seção: [IDs do aprovado que não vieram
        nas fontes]}, draft}. draft = currículo aprovado com os novos acrescentados e os IDs
        preservados; as alterações (changed) NÃO são aplicadas e nada é removido (o currículo geral é
        um superconjunto). Nada é salvo: revise com o usuário, aplique no draft o que ele aprovar e
        chame save_master_draft. Seções ausentes de items não geram "missing".
        """
        with resumes() as s:
            return s.diff_master(items)

    @server.tool()
    def approve_master() -> dict[str, Any]:
        """Promove o rascunho atual (inclusive edições feitas à mão) a currículo geral aprovado.

        Chamar SOMENTE quando o usuário disser explicitamente que revisou o rascunho e o aprova.
        Revalida o arquivo antes de aprovar. Aprovar conteúdo idêntico a uma versão existente não
        cria versão nova. Uma versão nova recalcula a aderência (match_score, match_terms) das
        candidaturas a_aplicar e pendente_usuario. Retorna {"created", "version_id", "content_hash",
        "rescored"} (rescored = candidaturas cuja aderência mudou).
        """
        with resumes() as s:
            return s.approve_master()

    @server.tool()
    def rescore_applications(status: Status | None = None) -> dict[str, Any]:
        """Recalcula a aderência (match_score, match_terms) das candidaturas com descrição, pelo
        currículo geral aprovado atual. Sem status: a_aplicar e pendente_usuario. Útil depois de mudar
        as regras de aderência; approve_master já faz isso ao aprovar uma versão nova.
        Retorna {"rescored": quantas mudaram, "unchanged"}."""
        with resumes() as s:
            return s.rescore_applications(status)

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
            return render_resume(master, resume_out or default_output_dir(db_path), label=label)

    @server.tool()
    def suggest_tailored_selection(application_id: int) -> dict[str, Any]:
        """Propõe a seleção inicial do currículo personalizado de uma candidatura, pelos termos da vaga.

        Chame ANTES de montar a seleção à mão: parta desta proposta, refine (corte, reordene, reescreva
        parágrafos em bullets que destaquem o que a vaga pede) e gere com create_tailored_resume.
        Usa os termos presentes no currículo ("matched" de match_terms da candidatura; sem eles,
        calcula pela descrição). Experiências na ordem do currículo, cada uma com os parágrafos que
        citam os termos primeiro (ao menos um parágrafo por experiência); voluntariado, projetos,
        publicações e certificações só com o que cita algum termo; skills com grupos e termos da vaga
        primeiro; formação e idiomas inteiros. A seleção já passa na validação de create_tailored_resume.
        Retorna {selection, scores: {paragraphs, items, skills}, terms, note}.
        """
        with resumes() as s:
            return s.suggest_tailored_selection(application_id)

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
        vinculado depois com add_application/update_application e resume_id). Passe-o sempre que o
        currículo for para uma vaga: o arquivo se chama "<Nome>_<Sobrenome>_Resume_<Empresa>_<Cargo>.pdf"
        (cargo longo é encurtado), para distinguir vagas da mesma empresa. Sem ele, o nome usa o label.
        Retorna {"id", "path", "windows_path", "pages", "warnings"}; o PDF vai para VAGAS_RESUME_OUT.
        windows_path é o caminho como o usuário o vê no Windows (null fora de /mnt/<letra>): use-o ao
        pedir que ele anexe o arquivo na vaga.
        """
        with resumes() as s:
            return s.create_tailored_resume(selection, resume_out or default_output_dir(db_path), application_id)

    @server.tool()
    def read_job_posting(url: str) -> dict[str, Any]:
        """Lê a página de uma vaga por código e devolve os campos já normalizados, sem você transcrever.

        Funciona com a Gupy, o LinkedIn Jobs (página pública, sem login) e páginas que publicam dados
        estruturados de vaga (muitos sites de carreira). Retorna {url, url_canonical, source, title,
        company, location, work_mode (remoto/hibrido/presencial), contract (clt/pj/desconhecido),
        role_key, seniority, role_certain, salary ({currency, period, min_value, max_value} se
        publicada; period null = confira na vaga), pcd_flag, published_at, closed, description};
        closed=true: o LinkedIn avisa que a vaga não aceita mais candidaturas (não se candidate nem
        registre); no LinkedIn também work_mode_inferred=true quando a modalidade veio do texto da descrição (confira).
        role_certain=false: confirme cargo e família pela descrição. LinkedIn limitou as leituras ou
        pediu login: erro; espere ou leia pelo navegador.
        Indeed e Glassdoor bloqueiam leitura automática: nesse caso (ou se a página não tiver dados
        estruturados) a tool devolve erro e você lê a vaga pelo navegador.
        """
        try:
            return fetch_job(url, fetcher=job_fetcher or http_fetch)
        except JobPostingError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def triage_job(url: str, search_id: int | None = None, not_duplicate: bool = False) -> dict[str, Any]:
        """Triagem completa de uma vaga numa chamada. Use SEMPRE para triar uma vaga a partir da URL.

        Encadeia, sem você repetir as etapas: find_application (URL), read_job_posting, critérios
        fixos do arquivo criterios-triagem.md (empresas ignoradas, vagas afirmativas/exclusivas PcD fora dos
        grupos que o usuário disputa, cargos alvo,
        locais aceitos), score_job_match, add_application (a_aplicar ou descartada, com search_id),
        faixa publicada (save_salary_estimate) e evaluate_salary pela política salarial.
        decision:
        - "ja_registrada": URL já registrada; siga pelo status de application, como em find_application;
        - "possivel_duplicata": nada registrado; a mesma empresa tem vaga de cargo e senioridade iguais
          (needs[0].matches). Pergunte ao usuário; se for outra vaga, chame de novo com not_duplicate=true;
        - "encerrada": o LinkedIn avisa que a vaga não aceita mais candidaturas; nada registrado, encerre a vaga;
        - "descartada": registrada como descartada (motivo em application.discard_reason);
        - "a_aplicar": registrada na lista de trabalho; resolva cada item de needs.
        needs = o que as regras não decidem, cada um {kind, detail} com a ação a tomar: "cargo" (cargo
        não reconhecido), "aderencia", "local" (híbrido/presencial fora dos locais aceitos), "modalidade",
        "senioridade", "afirmativa" (vaga afirmativa sem grupo reconhecido: leia e julgue),
        "pesquisa_salarial" (pesquise com as consultas em queries, as research_queries de
        evaluate_salary, e chame evaluate_salary de novo), "salario".
        Se o julgamento reprovar a vaga, use update_application com status "descartada".
        Página bloqueada ou sem dados estruturados: erro; leia a vaga pelo navegador e faça a triagem
        pelos passos manuais da Skill.
        Retorna {decision, application, posting (sem a descrição), match ({score, matched, missing,
        related, optional}, como em score_job_match), salary, reasons, needs}.
        """
        with triages() as t:
            return t.triage_job(url, search_id=search_id, not_duplicate=not_duplicate)

    @server.tool()
    def score_job_match(description: str, company: str | None = None, title: str | None = None,
                        location: str | None = None) -> dict[str, Any]:
        """Aderência de uma vaga ao currículo geral aprovado, a partir da descrição da vaga.

        Extrai só os termos técnicos da descrição (skills do currículo, tecnologias conhecidas,
        siglas, nomes como PyTorch ou C++) e separa os que aparecem no currículo geral ("matched")
        dos que não aparecem ("missing"). "score" é a proporção de presentes, de 0 a 100 (null se a
        descrição não tiver termos técnicos). Passe company, title e location da vaga: palavras
        deles são ignoradas. "related" = {termo ausente: [termos da mesma família no currículo]}
        (ex.: XGBoost ausente, relacionado LightGBM): lacuna de ferramenta, não de competência; não
        conta na nota. "optional" = termos que só aparecem em trechos de requisitos desejáveis
        ("Diferenciais", "Nice to have"): pesam metade na nota. A nota é INDICATIVA: use-a para justificar a triagem e para escolher o que
        destacar no currículo personalizado; a decisão de aplicar continua sendo da triagem.
        """
        with resumes() as s:
            return s.score_job_match(description, company=company, title=title, location=location)

    @server.tool()
    def list_resumes(application_id: int | None = None) -> dict[str, Any]:
        """Lista os currículos personalizados gerados, mais recentes primeiro: {"resumes": [...]}.
        Com application_id, só os vinculados àquela candidatura."""
        with resumes() as s:
            return {"resumes": s.list_resumes(application_id)}

    @server.tool()
    def get_resume(id: int) -> dict[str, Any]:
        """Retorna um currículo personalizado: seleção enviada, conteúdo final ("resolved"),
        versão do currículo geral de origem, caminho do PDF (pdf_path, e windows_path como o usuário o vê
        no Windows, ou null) e páginas."""
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
        ponto (CLT ou PJ); a conversão de regime é feita na avaliação. Cada ponto traz search_id
        (para discard_salary_estimate). Pesquisas descartadas não aparecem.
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
        Fontes aceitas: Glassdoor, LinkedIn Salary, Indeed Salários, Levels.fyi (empresa), guias
        salariais de recrutadoras (Robert Half, Michael Page, Hays) e a própria vaga. NÃO registre
        matérias jornalísticas, blogs nem posts que repetem números ("carreira que paga R$ 22 mil"):
        eles puxam a mediana para cima. Use só dados do mesmo cargo e senioridade.
        Sem company: dados de mercado para o cargo e senioridade. Moedas nunca são convertidas.
        Faixa salarial publicada na própria vaga: registre com source "vaga" e application_id da
        candidatura (e company); ela passa a ter prioridade na avaliação dessa vaga e não expira.
        Retorna {"search_id", "points"}.
        """
        with salaries() as s:
            return s.save_salary_estimate(role_key, seniority, currency, points, company=company, note=note,
                                          application_id=application_id)

    @server.tool()
    def discard_salary_estimate(search_id: int, reason: str) -> dict[str, Any]:
        """Descarta uma pesquisa salarial registrada que não serve: fonte fora das aceitas (matéria
        jornalística, blog), dado de outro cargo ou senioridade, valor transcrito errado. Ela deixa
        de contar em find_salary_estimate e evaluate_salary (fica no banco, com o motivo). search_id
        vem dos pontos de find_salary_estimate. Depois de descartar e pesquisar de novo, chame
        reevaluate_salaries. Retorna {search_id, discarded}."""
        with salaries() as s:
            return s.discard_salary_estimate(search_id, reason)

    @server.tool()
    def reevaluate_salaries() -> dict[str, Any]:
        """Refaz a avaliação salarial das vagas a_aplicar e pendente_usuario já avaliadas, com os dados
        frescos e a regra de pretensão atuais (salary_rule). Use depois de registrar ou descartar
        pesquisas salariais; set_config(salary_rule) já faz isso sozinho.
        Retorna {reevaluated, changed: [{id, company, role, url, decision, salary_market, before,
        after}], errors}. Vaga que passou a "nao_aplicar": descarte com update_application e o motivo
        de evaluate_salary (get_history). "pesquisar": faltam dados frescos."""
        with salaries() as s:
            return s.reevaluate_applications()

    @server.tool()
    def evaluate_salary(
        role_key: RoleKey,
        seniority: Seniority,
        currency: Currency,
        contract: Contract,
        work_mode: WorkMode | None = None,
        location: str | None = None,
        my_min: float | None = None,
        my_max: float | None = None,
        mode: SalaryMode | None = None,
        pj_multiplier: float | None = None,
        company: str | None = None,
        application_id: int | None = None,
    ) -> dict[str, Any]:
        """Triagem salarial de uma vaga e valor de pretensão a informar no formulário.

        Informe a modalidade (work_mode) e o local (location) da vaga: o MCP lê a política salarial
        (politica-salarial.md, em VAGAS_SALARY_POLICY) e escolhe sozinho a faixa, o modo e o
        multiplicador PJ; não leia nem interprete o arquivo. Com application_id, work_mode e
        location vêm da candidatura quando omitidos. my_min/my_max (faixa MENSAL em CLT), mode e
        pj_multiplier só para sobrepor a política. contract = regime da vaga (desconhecido é tratado
        como CLT); para vaga PJ a faixa CLT é multiplicada e o valor sai em PJ. Base: faixa
        publicada na vaga (application_id), senão dados frescos da empresa, senão de mercado. Com
        application_id, a avaliação fica gravada na candidatura (salary_evaluation, em get_history).
        Local não coberto pela política ou arquivo ausente/incompleto: erro dizendo o que corrigir.

        Pretensão (value_to_inform): sai do valor de referência (median) pela regra salary_rule do
        config: teto (a mediana), meio_termo (média entre o mínimo da política e a mediana),
        percentil_25 (quartil inferior das fontes) ou ponto_baixo (mediana do ponto baixo de cada
        fonte); nunca abaixo do mínimo nem acima do máximo (teto) da faixa da política. O teto só
        limita a pretensão (capped=true), não exclui a vaga. Com application_id, grava também as
        colunas salary_basis, salary_market, salary_rule e salary_ask da candidatura.

        decision: "aplicar" (use value_to_inform no campo de pretensão), "nao_aplicar" (registre a
        vaga como descartada usando reason como motivo) ou "pesquisar" (pesquise salários e chame
        save_salary_estimate antes). needs_research=true sugere pesquisar também a empresa.
        Retorna {decision, value_to_inform, rule, capped, basis, contract, median, range, sources,
        confidence, needs_research, reason, policy: {band, mode, my_min, my_max, pj_multiplier}, research_queries}.
        research_queries: quando faltam dados (decision "pesquisar" ou needs_research), consultas de
        pesquisa prontas, da mais específica à mais geral: cargo da vaga + empresa + cidade, cargo +
        empresa, empresa no Levels.fyi, mercado na cidade e no Brasil. Use na ordem e registre com
        save_salary_estimate: dado da empresa com company; empresa pesquisada sem dados também, com
        points vazio e company (evita repetir a busca); dado de mercado sem company. Remuneração total
        anual (ex.: Levels.fyi) vai com period "ano".
        """
        with salaries() as s:
            return s.evaluate_salary(
                role_key, seniority, currency, contract, my_min, my_max=my_max, mode=mode,
                pj_multiplier=pj_multiplier, company=company, application_id=application_id,
                work_mode=work_mode, location=location,
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
    def work_list() -> dict[str, Any]:
        """Lista de trabalho pronta: as vagas a_aplicar, da maior para a menor aderência, separadas em
        "ready" (prontas para candidatura) e "pending" (com pendência a resolver antes).

        Cada linha: {id, company, role, work_mode, contract (clt/pj/desconhecido), location, seniority, match_score, missing (principais
        termos ausentes), related ({ausente: [termos da mesma família no currículo]}), value_to_inform
        (pretensão, quando a avaliação salarial decidiu aplicar), salary_market (valor de referência:
        mediana da vaga, da empresa ou do mercado), salary_rule (regra da pretensão), salary_basis
        (vaga, empresa, mercado ou sem_dados), url, pending (lista:
        "modalidade", "senioridade", "salário não avaliado", "pesquisa salarial" ou o pending registrado)}.
        Retorna {ready, pending, counts, salary_rule: {value, chosen}}. Mostre as linhas como estão, sem
        recalcular. salary_rule.chosen=false: o usuário ainda não escolheu a regra da pretensão;
        pergunte (ver a skill) e grave com set_config.
        """
        with store(lambda conn: build_work_list(
                Repo(conn), ResumeStore(conn, draft_path or default_draft_path(db_path)))) as result:
            try:
                rule, source = paths_config.resolve("salary_rule", db_path)
            except VagasError as exc:
                raise ToolError(str(exc)) from exc
            return {**result, "salary_rule": {"value": rule, "chosen": source in ("env", "config")}}

    @server.tool()
    def start_search_run(
        sources: list[Source] | None = None,
        linkedin_remote_only: bool = True,
        max_pages: Annotated[int, Field(ge=1, le=5)] = 1,
    ) -> dict[str, Any]:
        """Executa a busca de vagas inteira em segundo plano: as buscas de suggest_job_searches (sem as
        recentes) e a triagem (triage_job) de cada vaga nova, com search_id. Use no lugar de chamar
        search_jobs e triage_job uma a uma. Leva de minutos a mais de meia hora (o LinkedIn exige 20 s
        entre requisições); acompanhe com get_search_run, sem esperar parado.
        sources: gupy e/ou linkedin (padrão: os dois). linkedin_remote_only: no LinkedIn, só as buscas
        remotas (padrão true; as por cidade são muitas). max_pages: páginas por busca (padrão 1).
        Só uma execução por vez. Retorna {run_id, status, params}.
        """
        with store(SearchRunStore) as runs:
            run_id = runs.create({"sources": sources, "linkedin_remote_only": linkedin_remote_only,
                                  "max_pages": max_pages})
            try:
                pid = (search_launcher or launch_search_run)(run_id)
            except OSError as exc:
                runs.fail(run_id, f"Não foi possível iniciar a busca: {exc}")
                raise ToolError(f"Não foi possível iniciar a busca em segundo plano: {exc}") from exc
            runs.set_pid(run_id, pid)
            run = runs.get(run_id)
        return {"run_id": run_id, "status": run["status"], "params": run["params"]}

    @server.tool()
    def get_search_run(run_id: int | None = None) -> dict[str, Any]:
        """Andamento e resultado de uma busca em lote (padrão: a mais recente).

        status: running, done, error ou interrompida. progress: {searches_total, searches_done,
        jobs_total, jobs_done, current}. Com status done, summary traz: searches {run, skipped
        (recentes), errors}; jobs {found, already_registered, triaged}; decisions (contagem por
        decisão); a_aplicar [{id, company, role, work_mode, location, match_score, url,
        value_to_inform, needs}]; descartadas [{id, company, role, reason}]; possiveis_duplicatas
        [{company, title, url, location, matches}] (pergunte ao usuário; se não for a mesma vaga, chame
        triage_job com not_duplicate=true); needs {tipo: [IDs]} (resolva como na triagem); errors.
        """
        with store(SearchRunStore) as runs:
            return runs.get(run_id)

    @server.tool()
    def suggest_job_searches() -> dict[str, Any]:
        """Sugere as buscas de vagas a executar, sem você montar as consultas.

        Combina os cargos alvo (e as "Senioridades buscadas", se houver) de criterios-triagem.md,
        em português e inglês, com os locais: remoto em todo o país e híbrido/presencial em cada
        local aceito, na Gupy e no LinkedIn (no LinkedIn, uma página e só vagas da última semana,
        porque ele limita leituras seguidas); acrescenta, por cargo, uma busca remota na Gupy com a
        skill mais citada nas experiências do currículo geral. recent=true: busca feita há pouco, pule.
        Retorna {"searches": [{query, source, location, filters, recent}], "skills", "note"}; passe
        cada busca (exceto as recentes) a search_jobs.
        """
        with boards() as b:
            return b.suggest_job_searches()

    @server.tool()
    def search_jobs(
        query: str,
        source: Source,
        location: str | None = None,
        filters: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Executa uma busca de vagas no site por código e registra a busca (save_job_search).

        Disponível para a Gupy e o LinkedIn (página pública, sem login); Indeed e Glassdoor bloqueiam
        leitura automática: erro, busque pelo navegador. Já consulta find_job_search: busca
        equivalente recente volta com skipped=true e sem resultados (force=true repete mesmo assim,
        só se o usuário pedir). location = cidade (LinkedIn sem location: Brasil inteiro).
        filters: {"work_modes": ["remoto"|"hibrido"|"presencial"], "max_pages": 1-5 (padrão 2; Gupy
        12 vagas por página, LinkedIn 10)}; só Gupy: "state"; só LinkedIn: "posted" ("24h", "week",
        "month"). No LinkedIn os resultados vêm sem modalidade (o filtro do site não é confiável) e
        cada página espera o intervalo do site (20 s). Bloqueio ou limite do site: erro; busque pelo
        navegador. Retorna {skipped, previous, search_id, total, pages_read, results: [{title,
        company, url, published_at, location, work_mode, contract, pcd_flag, salary, registered:
        {id, status} | null}]}.
        Depois, chame triage_job com a url e o search_id de cada resultado com registered null.
        """
        with boards() as b:
            return b.search_jobs(query, source, location=location, filters=filters, force=force)

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

    for tool in server._tool_manager.list_tools():  # os schemas vão ao modelo em toda conversa: sem rótulos redundantes
        tool.parameters = _without_titles(tool.parameters)
    return server


server = build_server()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    server.run("stdio")


if __name__ == "__main__":
    main()
