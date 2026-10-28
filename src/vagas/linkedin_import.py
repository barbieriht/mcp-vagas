"""Importação do perfil do LinkedIn do próprio usuário para o currículo geral. Não depende de MCP.

Orquestra: intervalo mínimo entre leituras -> leitor (navegador) -> parser -> registro como fonte.
"""

import os
from datetime import datetime, timedelta
from typing import Any, Protocol

from vagas.linkedin import LinkedInError, profile_base
from vagas.linkedin_parse import (
    certifications_text, parse_certifications, parse_education, parse_experience, parse_languages, parse_profile,
    parse_skills, parse_volunteering, section_text,
)
from vagas.repo import VagasError
from vagas.resume_repo import ResumeStore

DEFAULT_MIN_MINUTES = 60
SECTIONS = ("profile", "experience", "education", "certifications", "volunteering", "languages", "skills")


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

        warnings: list[str] = []
        experience, extras, found = parse_experience(blocks.get("experience", []))
        warnings += found
        education, found = parse_education(blocks.get("education", []), today=self.store.now()[:10])
        warnings += found
        groups, found = parse_certifications(blocks.get("certifications", []))
        warnings += found
        volunteering, found = parse_volunteering(blocks.get("volunteering", []))
        warnings += found
        profile = parse_profile(blocks.get("profile", ""))
        languages = parse_languages(blocks.get("languages", ""))
        skills = parse_skills(blocks.get("skills", []))
        if "headline" not in profile:
            warnings.append("Headline não encontrada na página do perfil.")
        if "summary" not in profile:
            warnings.append("Seção About não encontrada na página do perfil.")

        items = {**profile, "experience": experience, "education": education, "certifications": groups,
                 "volunteering": volunteering, "languages": languages, "skills": skills}
        counts = {"experience": len(experience), "education": len(education),
                  "certifications": sum(len(g["items"]) for g in groups), "volunteering": len(volunteering),
                  "languages": len(languages), "skills": sum(len(g["terms"]) for g in skills)}
        for section, count in counts.items():
            if count == 0:
                warnings.append(f"Nenhum item encontrado em {section}: confira se a seção existe no perfil.")
        texts = {
            "about": profile.get("summary", ""),
            "headline": profile.get("headline", ""),
            "languages": section_text(languages),
            "skills": "\n".join(line for group in skills for line in [group["label"], *group["terms"]]),
            "experience": section_text(experience, extras),
            "education": section_text(education),
            "certifications": certifications_text(groups),
            "volunteering": section_text(volunteering),
        }
        texts = {section: text for section, text in texts.items() if text}
        source = self.store.save_resume_source("linkedin", base, texts) if texts else None
        return {
            "items": items,
            "extras": extras,
            # A interface atual do LinkedIn não mostra o total nos botões "Show all": sem "expected".
            "completeness": {section: {"read": count, "expected": None, "verified": False}
                             for section, count in counts.items()},
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
