"""Valores fixos do domínio. Fonte única para o repo, o schema das tools e os testes."""

from typing import Literal, get_args

Status = Literal[
    "aplicada", "pendente_usuario", "rh", "tecnica", "gestor",
    "proposta", "recusada", "desistiu", "descartada",
]
InitialStatus = Literal["aplicada", "pendente_usuario", "descartada"]
Source = Literal["linkedin", "gupy", "indeed", "glassdoor", "outro"]
WorkMode = Literal["remoto", "hibrido", "presencial"]

STATUSES: tuple[str, ...] = get_args(Status)
INITIAL_STATUSES: tuple[str, ...] = get_args(InitialStatus)
SOURCES: tuple[str, ...] = get_args(Source)
WORK_MODES: tuple[str, ...] = get_args(WorkMode)
