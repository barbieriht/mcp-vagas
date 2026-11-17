"""Valores fixos do domínio. Fonte única para o repo, o schema das tools e os testes."""

from typing import Literal, get_args

Status = Literal[
    "a_aplicar", "aplicada", "pendente_usuario", "rh", "tecnica", "gestor",
    "proposta", "recusada", "desistiu", "descartada",
]
InitialStatus = Literal["a_aplicar", "aplicada", "pendente_usuario", "descartada"]
Source = Literal["linkedin", "gupy", "indeed", "glassdoor", "outro"]
WorkMode = Literal["remoto", "hibrido", "presencial"]

# Estimativas salariais
RoleKey = Literal["data_scientist", "ml_engineer", "ai_engineer", "data_engineer", "data_analyst", "outro"]
Seniority = Literal["estagio", "junior", "pleno", "senior", "especialista", "staff"]
Currency = Literal["BRL", "USD", "EUR"]
Period = Literal["hora", "mes", "ano"]
Contract = Literal["clt", "pj", "desconhecido"]
SalaryMode = Literal["minimo", "faixa"]
# Como a pretensão sai do valor de referência (mediana da vaga, da empresa ou do mercado):
# teto = a própria mediana; meio_termo = média entre o mínimo da política e a mediana;
# percentil_25 = quartil inferior das fontes; ponto_baixo = mediana do ponto baixo de cada fonte.
# Em todas, o máximo da faixa da política limita o valor (sem excluir a vaga).
SalaryRule = Literal["teto", "meio_termo", "percentil_25", "ponto_baixo"]

# Nomes de cada família de cargo (português, inglês): consultas de busca e valores aceitos nos critérios.
ROLE_NAMES: dict[str, tuple[str, str]] = {
    "data_scientist": ("cientista de dados", "data scientist"),
    "ml_engineer": ("engenheiro de machine learning", "machine learning engineer"),
    "ai_engineer": ("engenheiro de ia", "ai engineer"),
    "data_engineer": ("engenheiro de dados", "data engineer"),
    "data_analyst": ("analista de dados", "data analyst"),
}

# Senioridade como se escreve nas buscas.
SENIORITY_LABELS: dict[str, str] = {"estagio": "estágio", "junior": "júnior", "pleno": "pleno", "senior": "sênior",
                                    "especialista": "especialista", "staff": "staff"}

# Pendências estruturadas de uma candidatura (pending_items)
PendingKind = Literal["diversidade", "consentimento", "anexo_curriculo", "documento_cofre", "resposta_aberta", "login"]

# O que a triagem não decide e deixa para julgar (needs), gravado na candidatura
NeedKind = Literal["cargo", "local", "modalidade", "senioridade", "aderencia", "afirmativa", "pesquisa_salarial",
                   "salario"]
# Etapas de um processo em andamento: alterações em lote só as tocam se o filtro as citar
PROTECTED_STATUSES: tuple[str, ...] = ("aplicada", "rh", "tecnica", "gestor", "proposta")
# Colunas que query_applications devolve (sem a descrição nem a avaliação salarial completa)
QueryField = Literal[
    "id", "company", "role", "url", "source", "status", "seniority", "work_mode", "location", "contract",
    "match_score", "match_terms", "needs", "pending", "discard_reason", "salary_ask", "salary_market",
    "salary_basis", "search_id", "form_url", "created_at", "updated_at", "last_event_at",
]
QueryOrder = Literal["-created_at", "created_at", "-match_score", "match_score", "company", "id", "-id"]

# Fontes do currículo geral
ResumeSourceKind = Literal["linkedin", "pdf"]
LinkedInSection = Literal[
    "about", "headline", "experience", "education", "certifications", "volunteering", "languages", "skills",
]

STATUSES: tuple[str, ...] = get_args(Status)
INITIAL_STATUSES: tuple[str, ...] = get_args(InitialStatus)
SOURCES: tuple[str, ...] = get_args(Source)
WORK_MODES: tuple[str, ...] = get_args(WorkMode)
ROLE_KEYS: tuple[str, ...] = get_args(RoleKey)
SENIORITIES: tuple[str, ...] = get_args(Seniority)
CURRENCIES: tuple[str, ...] = get_args(Currency)
CONTRACTS: tuple[str, ...] = get_args(Contract)
SALARY_MODES: tuple[str, ...] = get_args(SalaryMode)
SALARY_RULES: tuple[str, ...] = get_args(SalaryRule)
RESUME_SOURCE_KINDS: tuple[str, ...] = get_args(ResumeSourceKind)
LINKEDIN_SECTIONS: tuple[str, ...] = get_args(LinkedInSection)
PENDING_KINDS: tuple[str, ...] = get_args(PendingKind)
NEED_KINDS: tuple[str, ...] = get_args(NeedKind)
QUERY_FIELDS: tuple[str, ...] = get_args(QueryField)
