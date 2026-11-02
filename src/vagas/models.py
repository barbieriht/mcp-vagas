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
Seniority = Literal["estagio", "junior", "pleno", "senior", "especialista"]
Currency = Literal["BRL", "USD", "EUR"]
Period = Literal["hora", "mes", "ano"]
Contract = Literal["clt", "pj", "desconhecido"]
SalaryMode = Literal["minimo", "faixa"]

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
                                    "especialista": "especialista"}

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
RESUME_SOURCE_KINDS: tuple[str, ...] = get_args(ResumeSourceKind)
LINKEDIN_SECTIONS: tuple[str, ...] = get_args(LinkedInSection)
