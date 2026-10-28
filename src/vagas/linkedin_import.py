"""Importação do perfil do LinkedIn do próprio usuário para o currículo geral. Não depende de MCP.

Orquestra: intervalo mínimo entre leituras -> leitor (navegador) -> parser -> registro como fonte.
"""

import os
from datetime import datetime, timedelta
from typing import Any, Protocol

from vagas.linkedin import LinkedInError, profile_base
from vagas.linkedin_parse import certifications_text, parse_certifications
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore

DEFAULT_MIN_MINUTES = 60
SECTIONS = ("certifications",)


class Reader(Protocol):
    def read_sections(self, url: str, sections: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]: ...


def _min_interval() -> timedelta:
    return timedelta(minutes=float(os.environ.get("VAGAS_LINKEDIN_MIN_MINUTES") or DEFAULT_MIN_MINUTES))


class LinkedInImporter:
    def __init__(self, store: ResumeStore, reader: Reader):
        self.store = store
        self.reader = reader

    def import_profile(self, url: str) -> dict[str, Any]:
        try:
            base = profile_base(url)
        except LinkedInError as exc:
            raise VagasError(str(exc)) from exc
        self._check_interval()
        try:
            blocks = self.reader.read_sections(base, SECTIONS)
        except LinkedInError as exc:
            raise VagasError(str(exc)) from exc

        groups, warnings = parse_certifications(blocks.get("certifications", []))
        read = sum(len(group["items"]) for group in groups)
        if read == 0:
            warnings.append("Nenhum item encontrado em certifications: confira se a seção existe no perfil.")
        source = self.store.save_resume_source("linkedin", base, {"certifications": certifications_text(groups)}) \
            if read else None
        return {
            "items": {"certifications": groups},
            # A interface atual do LinkedIn não mostra o total nos botões "Show all": sem "expected".
            "completeness": {"certifications": {"read": read, "expected": None, "verified": False}},
            "warnings": warnings,
            "source_id": source and source["source_id"],
        }

    def _check_interval(self) -> None:
        row = self.store.conn.execute(
            "SELECT extracted_at FROM resume_sources WHERE kind = 'linkedin' ORDER BY extracted_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return
        elapsed = datetime.fromisoformat(self.store.now()) - datetime.fromisoformat(row["extracted_at"])
        wait = _min_interval() - elapsed
        if wait > timedelta(0):
            minutes = int(wait.total_seconds() // 60) + 1
            raise VagasError(
                f"O LinkedIn foi lido há pouco; respeite o intervalo mínimo entre leituras (faltam {minutes} min). "
                "Use os dados já registrados ou tente mais tarde."
            )
