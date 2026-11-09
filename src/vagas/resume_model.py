"""Modelo do currículo geral (fonte única da verdade para os currículos personalizados)."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

Id = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
WorkMode = Literal["remote", "hybrid", "onsite"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Basics(_Model):
    name: Text
    headline: Text | None = None
    headline_variants: list[Text] = Field([], description="Outras headlines usadas nas fontes (ex.: LinkedIn)")
    email: Text | None = None
    phone: Text | None = None
    location: Text | None = None
    links: list[Text] = []


class Paragraph(_Model):
    id: Id
    text: Text


class Education(_Model):
    id: Id
    institution: Text
    degree: Text
    field: Text | None = None
    notes: Text | None = None
    start: Text | None = None
    end: Text | None = None


class Experience(_Model):
    id: Id
    company: Text
    context: Text | None = Field(None, description="Ex.: projeto financiado ao qual a função pertence")
    title: Text
    title_aliases: list[Text] = Field([], description="Outras formas do título usadas nas fontes")
    location: Text | None = Field(None, description="Cidade do escritório")
    work_mode: WorkMode | None = None
    start: Text
    end: Text | None = Field(None, description='Vazio ou "Present" para função atual')
    paragraphs: list[Paragraph] = Field(min_length=1)


class Volunteering(_Model):
    id: Id
    organization: Text
    role: Text
    location: Text | None = None
    work_mode: WorkMode | None = None
    start: Text | None = None
    end: Text | None = None
    paragraphs: list[Paragraph] = []


class Project(_Model):
    id: Id
    name: Text
    link: Text | None = None
    start: Text | None = None
    end: Text | None = None
    paragraphs: list[Paragraph] = []


class Publication(_Model):
    id: Id
    title: Text
    venue: Text | None = None
    year: int | None = None
    authors: Text | None = None
    link: Text | None = None


class SkillGroup(_Model):
    id: Id
    label: Text
    terms: list[Text] = Field(min_length=1)


class Certification(_Model):
    id: Id
    name: Text = Field(description="Título em inglês (é o que sai no currículo)")
    name_original: Text | None = Field(None, description="Título exato da credencial, se não estiver em inglês")
    provider: Text | None = None
    year: int | None = None
    issued: Annotated[str, StringConstraints(pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$")] | None = Field(
        None, description="Emissão: YYYY-MM (ou YYYY)")
    credential_id: Text | None = Field(None, description="ID da credencial; único no currículo")
    link: Text | None = Field(None, description="URL da credencial, quando houver")
    description: Text | None = Field(
        None, description="Descrição do curso; guardada, mas não vale como experiência nos personalizados")

    @model_validator(mode="after")
    def _issued_matches_year(self) -> "Certification":
        if self.issued and self.year is not None and int(self.issued[:4]) != self.year:
            raise ValueError(f"issued ({self.issued}) e year ({self.year}) não concordam em {self.id}")
        return self


class CertificationGroup(_Model):
    id: Id
    label: Text
    items: list[Certification] = Field(min_length=1)


class Language(_Model):
    name: Text
    level: Text
    note: Text | None = Field(None, description=(
        'Complemento impresso ao lado do nível, como a certificação (ex.: "Certification (CEPE Idiomas)"). '
        'Nunca de onde veio a informação ou como as fontes divergem ("PDF lists...", "LinkedIn: ...")'))


class MasterResume(_Model):
    """Currículo geral em inglês. IDs são slugs (minúsculas, dígitos e hífens) únicos no documento
    e devem distinguir funções na mesma empresa (ex.: exp-empresa-cargo, exp-empresa-cargo-p1)."""

    basics: Basics
    summary: Text | None = None
    education: list[Education] = []
    experience: list[Experience] = []
    volunteering: list[Volunteering] = []
    projects: list[Project] = []
    publications: list[Publication] = []
    skills: list[SkillGroup] = []
    certifications: list[CertificationGroup] = []
    languages: list[Language] = []

    @model_validator(mode="after")
    def _unique_credentials(self) -> "MasterResume":
        seen: dict[str, str] = {}
        for group in self.certifications:
            for cert in group.items:
                if cert.credential_id is None:
                    continue
                if cert.credential_id in seen:
                    raise ValueError(
                        f"credential_id {cert.credential_id!r} repetido em {seen[cert.credential_id]} e {cert.id}: "
                        "é a mesma credencial; funda os itens mantendo a data de emissão mais antiga e avise o "
                        "usuário para corrigir a fonte"
                    )
                seen[cert.credential_id] = cert.id
        return self

    @model_validator(mode="after")
    def _unique_ids(self) -> "MasterResume":
        seen: dict[str, str] = {}
        for location, item_id in _ids(self):
            if item_id in seen:
                raise ValueError(f"ID duplicado {item_id!r} em {location} (já usado em {seen[item_id]})")
            seen[item_id] = location
        return self

    def as_data(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True, exclude_defaults=True)


def _ids(resume: MasterResume):
    for section in ("education", "experience", "volunteering", "projects", "publications", "skills",
                    "certifications"):
        for i, item in enumerate(getattr(resume, section)):
            yield f"{section}.{i}.id", item.id
            for j, paragraph in enumerate(getattr(item, "paragraphs", [])):
                yield f"{section}.{i}.paragraphs.{j}.id", paragraph.id
            for j, cert in enumerate(getattr(item, "items", [])):
                yield f"{section}.{i}.items.{j}.id", cert.id


def describe_errors(exc: ValidationError, title: str = "Currículo inválido") -> str:
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        value = f" (valor: {error['input']!r})" if isinstance(error.get("input"), str) else ""
        lines.append(f"- {location}: {message}{value}" if location else f"- {message}")
    return f"{title}:\n" + "\n".join(lines)
