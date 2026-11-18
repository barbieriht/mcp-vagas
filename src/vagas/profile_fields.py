"""Campos de formulário no perfil da Skill (perfil.md, pessoal, e perfil.example.md, versionado). Não depende de MCP.

O perfil é Markdown: seções "## <nome>" com itens "- <rótulo>: <valor>". Um campo novo entra nos dois
arquivos, na mesma seção: no perfil com o valor (ou <PREENCHER>), no exemplo com <...>. Dados
sensíveis (documentos, senhas, dados bancários) nunca são guardados: ficam como "informar manualmente".
"""

import hashlib
import os
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from vagas import diversity, generic_questions, languages
from vagas.normalize import normalize_text
from vagas.repo import VagasError
from vagas.salary_policy import default_policy_path

OTHER_SECTION = "Outros campos de formulário"
CREATABLE = (diversity.SECTION, "Consentimentos")  # seções que um campo novo cria, antes de OTHER_SECTION
MANUAL = "informar manualmente"
PLACEHOLDER = "<PREENCHER>"
_ITEM = re.compile(r"^- (?P<label>[^:]+):\s*(?P<value>.*)$")
_SENSITIVE = re.compile(r"\b(cpf|rg|cnh|pis|pasep|nis|ctps|passaporte|passport|senha|password|conta bancaria"
                        r"|agencia|cartao|cvv|titulo de eleitor|certidao)\b")


def default_skill_dir(db_path: Path | str | None = None) -> Path:
    """VAGAS_SKILL_DIR; senão a pasta para onde aponta o symlink da política salarial (criado pelo instalador)."""
    if env := os.environ.get("VAGAS_SKILL_DIR"):
        return Path(env)
    policy = default_policy_path(db_path)
    if policy.is_symlink() and (policy.resolve().parent / "perfil.example.md").exists():
        return policy.resolve().parent
    raise VagasError("Pasta da Skill não encontrada: defina VAGAS_SKILL_DIR com a pasta skill/candidaturas do "
                     "repositório (ou rode o instalador, que liga a política salarial a ela).")


def _key(label: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", normalize_text(label)))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _label(line: str) -> str:
    return _ITEM.match(line)["label"].strip()


def disability_answer(db_path: Path | str | None = None) -> str | None:
    """"Possui deficiência" do perfil da Skill, para a triagem; None sem o campo ou sem a pasta da Skill."""
    try:
        return ProfileFiles(default_skill_dir(db_path)).disability()
    except VagasError:
        return None


def is_sensitive(label: str) -> bool:
    return _SENSITIVE.search(normalize_text(label)) is not None


class _Profile:
    def __init__(self, path: Path):
        if not path.exists():
            raise VagasError(f"Arquivo de perfil não encontrado: {path}. Crie perfil.md a partir de perfil.example.md.")
        self.path = path
        self.lines = path.read_text(encoding="utf-8").splitlines()

    def save(self) -> None:
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def sections(self) -> list[tuple[int, str]]:
        return [(i, line[3:].strip()) for i, line in enumerate(self.lines) if line.startswith("## ")]

    def find(self, label: str) -> int | None:
        key = _key(label)
        return next((i for i, line in enumerate(self.lines) if (m := _ITEM.match(line)) and _key(m["label"]) == key),
                    None)

    def section(self, wanted: str, create: bool) -> tuple[int, str] | None:
        key = _key(wanted)
        for index, name in self.sections():
            if _key(name) == key or key in _key(name):
                return index, name
        if not create:
            return None
        while self.lines and not self.lines[-1].strip():
            self.lines.pop()
        self.lines += ["", f"## {wanted}"]
        return len(self.lines) - 1, wanted

    def block_end(self, index: int) -> int:
        """Fim do bloco do campo na linha index: a linha depois dos subitens indentados."""
        end = index + 1
        while end < len(self.lines) and self.lines[end].strip() and self.lines[end][:1] in (" ", "\t"):
            end += 1
        return end

    def old_diversity(self) -> tuple[int, int, list[str]] | None:
        """O campo "Diversidade" do formato antigo: (início, fim, textos dos subitens)."""
        for i, line in enumerate(self.lines):
            if (m := _ITEM.match(line)) and diversity.is_old_block(m["label"]):
                end = self.block_end(i)
                children = [c.strip()[2:].strip() for c in self.lines[i + 1:end] if c.strip().startswith("- ")]
                return i, end, children
        return None

    def section_before(self, wanted: str, before: str) -> tuple[int, str]:
        """A seção; sem ela, cria antes da seção `before` (ou no fim)."""
        found = self.section(wanted, create=False)
        if found is not None:
            return found
        anchor = self.section(before, create=False)
        if anchor is None:
            return self.section(wanted, create=True)
        self.lines[anchor[0]:anchor[0]] = [f"## {wanted}", ""]
        return anchor[0], wanted

    def insert(self, header: int, line: str) -> None:
        end = next((i for i in range(header + 1, len(self.lines)) if self.lines[i].startswith("## ")), len(self.lines))
        last = max((i for i in range(header, end) if self.lines[i].strip()), default=header)
        self.lines.insert(last + 1, line)


VAULT = "no cofre (extensão do Chrome)"
TALENT_POOL = "Incluir em bancos de talentos"


class ProfileFiles:
    def __init__(self, skill_dir: Path | str):
        self.dir = Path(skill_dir)

    def get_profile(self, vault_fields: list[str], declined: Collection[str] = ()) -> dict[str, Any]:
        """Perfil estruturado: seções e campos com status (ok, preencher, manual, cofre, cofre_vazio, migrar),
        subitens como observações. Campos do cofre nunca trazem o valor, só a indicação.

        `migration` é a próxima proposta de mudança de formato, para o usuário confirmar (uma por vez, `kind`):
        "diversidade" (respostas no formato antigo, subitens de "Diversidade", que nunca saem como observações: o
        campo fica "migrar"), "idiomas" (nível declarado e certificado na mesma linha de "Idiomas") ou
        "campos_genericos" (campos que o MCP passou a responder sozinho, como os criados um por empresa; `removed`
        lista os que saem). `declined`
        são os ids das propostas que ele recusou: elas não voltam (o campo antigo de diversidade fica
        "preencher")."""
        from vagas.sensitive import ALLOWED_FIELDS

        by_label = {_key(label): field for field, label in ALLOWED_FIELDS.items()}
        perfil = _Profile(self.dir / "perfil.md")
        sections: list[dict[str, Any]] = []
        to_fill: list[str] = []
        vault_missing: list[str] = []
        current = None
        old = perfil.old_diversity()
        old_line = perfil.lines[old[0]] if old and old[2] else None
        proposals = self._migrations(perfil)
        migration = next((m for m in proposals if m["id"] not in declined), None)
        offered = any(m["kind"] == "diversidade" and m["id"] not in declined for m in proposals)
        for line in perfil.lines:
            if line.startswith("## "):
                sections.append({"name": line[3:].strip(), "fields": []})
                continue
            if not sections:
                continue
            item = _ITEM.match(line)
            if item:
                label, value = item["label"].strip(), item["value"].strip()
                field: dict[str, Any] = {"label": label, "value": value, "status": "ok", "notes": []}
                if line == old_line:
                    field["value"], field["status"] = "", "migrar" if offered else "preencher"
                    if not offered:
                        to_fill.append(label)
                elif value.startswith("<"):
                    field["status"] = "preencher"
                    to_fill.append(label)
                elif _key(value) == _key(MANUAL) and by_label.get(_key(label)) in vault_fields:
                    # Documento cadastrado no cofre vale mais que um "informar manualmente" desatualizado.
                    field["vault_field"], field["status"] = by_label[_key(label)], "cofre"
                elif _key(value) == _key(MANUAL):
                    field["status"] = "manual"
                elif re.match(r"(no )?cofre\b", normalize_text(value)):  # "no cofre (...)", "cofre", "Cofre."
                    vault_field = by_label.get(_key(label))
                    field["vault_field"] = vault_field
                    field["status"] = "cofre" if vault_field in vault_fields else "cofre_vazio"
                    if field["status"] == "cofre_vazio":
                        vault_missing.append(label)
                sections[-1]["fields"].append(field)
                current = field
            elif line.startswith((" ", "\t")) and line.strip().startswith("- ") and current is not None:
                if current["status"] not in ("migrar",) and not (old_line and current["label"] == _label(old_line)):
                    current["notes"].append(line.strip()[2:].strip())
        result: dict[str, Any] = {"sections": sections, "to_fill": to_fill, "vault_missing": vault_missing}
        if migration is not None:
            result["migration"] = migration
        warnings = []
        if old_line and offered:
            warnings.append(
                "As respostas de diversidade estão no formato antigo (subitens do campo \"Diversidade\") e não valem "
                "nos formulários. Mostre ao usuário os campos de 'migration' (valor proposto e o texto de origem) e "
                "pergunte se confirma; com a resposta dele, chame apply_profile_migration (accept true ou false).")
        elif old_line:
            warnings.append(
                "O usuário recusou migrar as respostas de diversidade do formato antigo: elas não valem nos formulários. "
                f"Pergunte cada uma quando um formulário pedir e grave com add_profile_field (section \"{diversity.SECTION}\").")
        if migration is not None and migration["kind"] == "campos_genericos":
            warnings.append(
                "O perfil tem campos criados um por empresa (\"Você trabalha na empresa X?\", \"Foi indicado?\"), que "
                "agora são respondidos por campos genéricos. Mostre ao usuário os campos de 'migration' (os que saem "
                "em 'removed' e os que entram em 'fields') e pergunte se confirma; com a resposta dele, chame "
                "apply_profile_migration (accept true ou false).")
        if migration is not None and migration["kind"] == "idiomas":
            warnings.append(
                "\"Idiomas\" junta o nível declarado e o certificado (formato antigo). Mostre ao usuário os campos de "
                "'migration' (valor proposto e o texto de origem) e pergunte se confirma; com a resposta dele, chame "
                "apply_profile_migration (accept true ou false).")
        if warnings:
            result["warnings"] = warnings
        return result

    def _migrations(self, perfil: "_Profile") -> list[dict[str, Any]]:
        """Propostas de mudança de formato, na ordem em que são oferecidas."""
        return [m for m in (self._migration(perfil), self._languages_migration(perfil), self._generic_migration(perfil))
                if m is not None]

    def _migration(self, perfil: "_Profile") -> dict[str, Any] | None:
        old = perfil.old_diversity()
        if old is None or not old[2]:
            return None
        present = {m["label"].strip() for line in perfil.lines if (m := _ITEM.match(line))}
        fields = diversity.proposal(old[2], present)
        block = "\n".join(perfil.lines[old[0]:old[1]])
        return {"kind": "diversidade", "id": _digest(block), "section": diversity.SECTION, "fields": fields}

    def _languages_migration(self, perfil: "_Profile") -> dict[str, Any] | None:
        """"Idiomas" no formato antigo ("inglês avançado (B2, certificado)"): propõe o nível declarado em "Idiomas" e
        o certificado em "Certificações de idiomas" (somado ao que esse campo já tiver)."""
        index = perfil.find(languages.LANGUAGES_LABEL)
        if index is None:
            return None
        old = _ITEM.match(perfil.lines[index])["value"].strip()
        found = languages.split(old) if not old.startswith("<") else None
        if found is None:
            return None
        declared, certifications = found
        cert_index = perfil.find(languages.CERTIFICATIONS_LABEL)
        current = _ITEM.match(perfil.lines[cert_index])["value"].strip() if cert_index is not None else ""
        kept = [] if current.startswith("<") else languages.split_top(current)
        known = {languages.key(r["language"]) for r in languages.parse_languages(", ".join(kept))}
        merged = kept + [c for c in certifications if languages.key(c) not in known or languages.key(c) is None]
        block = "\n".join(perfil.lines[index:perfil.block_end(index)])
        section = next((n for i, n in reversed(perfil.sections()) if i < index), "")
        return {"kind": "idiomas", "id": _digest(block + current), "section": section, "fields": [
            {"label": languages.LANGUAGES_LABEL, "value": declared, "from": old},
            {"label": languages.CERTIFICATIONS_LABEL, "value": ", ".join(merged), "from": old}]}

    def _generic_migration(self, perfil: "_Profile") -> dict[str, Any] | None:
        """Campos que o MCP passou a responder sozinho: os criados um por empresa ("Você trabalha na empresa X?",
        "É colaborador X?", "Foi indicado?"), "Trabalha atualmente" e "Já trabalhou na empresa da vaga" (currículo
        geral), "Minimum Pay" (política salarial) e os de emprego atual ainda sem resposta ("Salário Atual").
        Propõe tirá-los; fica um "Sim" de trabalha ou trabalhou numa empresa (pode não estar no currículo). A
        resposta de indicação passa para "Foi indicado por alguém da empresa" quando todas concordam."""
        removed, referrals = [], []
        keep = {_key(generic_questions.REFERRAL_LABEL), _key(generic_questions.LAST_PAY_LABEL)}
        derived = {_key(generic_questions.CURRENT_LABEL), _key(generic_questions.PAST_LABEL)}
        for line in perfil.lines:
            item = _ITEM.match(line)
            if not item or line.startswith((" ", "\t")):
                continue
            label, value = item["label"].strip(), item["value"].strip()
            if _key(label) in keep:
                continue
            filled = None if value.startswith("<") else value
            if _key(label) in derived:
                removed.append({"label": label, "value": filled})
                continue
            kind = generic_questions.kind(re.sub(r"\s*\(op[cç][oõ]es\b.*$", "", label))
            if kind is None:
                continue
            if kind == generic_questions.MIN_PAY:
                removed.append({"label": label, "value": filled})
                continue
            if kind in generic_questions.JOB_KINDS:  # "Salário Atual": sai só o que ainda não tem resposta
                if filled is None:
                    removed.append({"label": label, "value": None})
                continue
            answer = generic_questions.yes_no(value)
            if kind != generic_questions.REFERRAL and answer == "Sim":
                continue
            removed.append({"label": label, "value": filled})
            if kind == generic_questions.REFERRAL and answer:
                referrals.append(answer)
        if not removed:
            return None
        fields = []
        if perfil.find(generic_questions.REFERRAL_LABEL) is None:
            value = referrals[0] if referrals and len(set(referrals)) == 1 else None
            fields.append({"label": generic_questions.REFERRAL_LABEL, "value": value, "from": None})
        block = "\n".join(f"{r['label']}: {r['value']}" for r in removed)
        return {"kind": "campos_genericos", "id": _digest(block), "section": generic_questions.SECTION,
                "fields": fields, "removed": removed}

    def _apply_generic(self, migration: dict[str, Any]) -> dict[str, Any]:
        labels = {_key(r["label"]) for r in migration["removed"]}
        label = generic_questions.REFERRAL_LABEL
        for name, filled in (("perfil.md", True), ("perfil.example.md", False)):
            profile = _Profile(self.dir / name)
            index = 0
            while index < len(profile.lines):
                item = _ITEM.match(profile.lines[index])
                if item and _key(item["label"]) in labels:
                    del profile.lines[index:profile.block_end(index)]
                else:
                    index += 1
            fields = {f["label"]: f["value"] for f in migration["fields"]}
            if profile.find(label) is None and (label in fields or not filled):
                header, _ = profile.section(generic_questions.SECTION, create=True)
                value = (fields.get(label) or PLACEHOLDER) if filled else "<...>"
                profile.insert(header, f"- {label}: {value}")
                profile.insert(header, f"  - {generic_questions.REFERRAL_NOTE}")
            profile.save()
        return {"written": [f["label"] for f in migration["fields"] if f["value"]],
                "to_fill": [f["label"] for f in migration["fields"] if not f["value"]],
                "removed": [r["label"] for r in migration["removed"]]}

    def apply_migration(self, declined: Collection[str] = ()) -> dict[str, Any]:
        """Grava a proposta que get_profile mostra (a primeira não recusada; sem ela, a primeira recusada, que o
        usuário pediu para aplicar depois). Retorna {kind, written, to_fill}."""
        perfil = _Profile(self.dir / "perfil.md")
        proposals = self._migrations(perfil)
        if not proposals:
            raise VagasError("Não há proposta de migração no perfil.")
        chosen = next((m for m in proposals if m["id"] not in declined), proposals[0])
        if chosen["kind"] == "idiomas":
            return {"kind": "idiomas", **self._apply_languages(perfil, chosen)}
        if chosen["kind"] == "campos_genericos":
            return {"kind": "campos_genericos", **self._apply_generic(chosen)}
        return {"kind": "diversidade", **self.apply_diversity_migration()}

    def _apply_languages(self, perfil: "_Profile", migration: dict[str, Any]) -> dict[str, Any]:
        declared, certifications = (f["value"] for f in migration["fields"])
        index = perfil.find(languages.LANGUAGES_LABEL)
        end = perfil.block_end(index)
        notes = [line for line in perfil.lines[index + 1:end]
                 if not languages.is_legacy_note(line.strip().removeprefix("- "))]
        if not any(languages.LANGUAGES_NOTE in line for line in notes):
            notes.insert(0, f"  - {languages.LANGUAGES_NOTE}")
        label = _ITEM.match(perfil.lines[index])["label"].strip()
        perfil.lines[index:end] = [f"- {label}: {declared}", *notes]
        cert_index = perfil.find(languages.CERTIFICATIONS_LABEL)
        if cert_index is not None:
            cert_label = _ITEM.match(perfil.lines[cert_index])["label"].strip()
            perfil.lines[cert_index] = f"- {cert_label}: {certifications}"
        else:
            at = perfil.block_end(index)
            perfil.lines[at:at] = [f"- {languages.CERTIFICATIONS_LABEL}: {certifications}",
                                   f"  - {languages.CERTIFICATIONS_NOTE}"]
        perfil.save()
        example = _Profile(self.dir / "perfil.example.md")
        if example.find(languages.CERTIFICATIONS_LABEL) is None:
            anchor = example.find(languages.LANGUAGES_LABEL)
            at = example.block_end(anchor) if anchor is not None else None
            if at is None:
                header, _ = example.section("Respostas padrão", create=True)
                example.insert(header, f"- {languages.CERTIFICATIONS_LABEL}: <...>")
            else:
                example.lines[at:at] = [f"- {languages.CERTIFICATIONS_LABEL}: <...>"]
            example.save()
        return {"written": [languages.LANGUAGES_LABEL, languages.CERTIFICATIONS_LABEL], "to_fill": []}

    def apply_diversity_migration(self) -> dict[str, Any]:
        """Grava a proposta de `migration`: um campo por pergunta na seção "Diversidade e inclusão" (sem resposta,
        <PREENCHER>) e tira o campo antigo com os subitens. O exemplo recebe os campos com <...>."""
        perfil = _Profile(self.dir / "perfil.md")
        migration = self._migration(perfil)
        if migration is None:
            raise VagasError("Não há respostas de diversidade no formato antigo para migrar.")
        start, end, _ = perfil.old_diversity()
        del perfil.lines[start:end]
        header, _ = perfil.section_before(diversity.SECTION, OTHER_SECTION)
        for row in migration["fields"]:
            perfil.insert(header, f"- {row['label']}: {row['value'] or PLACEHOLDER}")
        perfil.save()
        example = _Profile(self.dir / "perfil.example.md")
        if (old := example.old_diversity()) is not None:
            del example.lines[old[0]:old[1]]
        header, _ = example.section_before(diversity.SECTION, OTHER_SECTION)
        for q in diversity.QUESTIONS:
            if example.find(q.label) is None:
                example.insert(header, f"- {q.label}: <...>")
        example.save()
        return {"written": [r["label"] for r in migration["fields"] if r["value"]],
                "to_fill": [r["label"] for r in migration["fields"] if not r["value"]]}

    def data_consent(self) -> bool | None:
        """"Autorizar uso de dados para recrutamento" do perfil: True (autorizo), False (não autorizo) ou None."""
        from vagas import consents

        path = self.dir / "perfil.md"
        if not path.exists():
            return None
        perfil = _Profile(path)
        index = perfil.find(consents.DATA)
        return consents.yes(_ITEM.match(perfil.lines[index])["value"]) if index is not None else None

    def disability(self) -> str | None:
        """"Possui deficiência" do perfil (diversity.disability); None sem o campo."""
        path = self.dir / "perfil.md"
        if not path.exists():
            return None
        perfil = _Profile(path)
        index = perfil.find(diversity.DISABILITY)
        if index is None:
            return None
        return diversity.disability(_ITEM.match(perfil.lines[index])["value"])

    def talent_pool(self) -> bool | None:
        """Resposta de "Incluir em bancos de talentos" no perfil.md: True (sim), False (não) ou None (sem resposta)."""
        path = self.dir / "perfil.md"
        if not path.exists():
            return None
        perfil = _Profile(path)
        index = perfil.find(TALENT_POOL)
        if index is None:
            return None
        answer = _key(_ITEM.match(perfil.lines[index])["value"]).split(" ")[0]
        return {"sim": True, "s": True, "yes": True, "nao": False, "n": False, "no": False}.get(answer)

    def mark_vault(self, label: str, stored: bool) -> None:
        """No perfil.md, o campo sensível fica "no cofre" ou volta a "informar manualmente" (nunca o valor)."""
        perfil = _Profile(self.dir / "perfil.md")
        if perfil.find(label) is None:
            self.add_profile_field(label, sensitive=True)
            perfil = _Profile(self.dir / "perfil.md")
        index = perfil.find(label)
        current = _ITEM.match(perfil.lines[index])
        perfil.lines[index] = f"- {current['label']}: {VAULT if stored else MANUAL}"
        perfil.save()

    def add_profile_field(self, label: str, section: str | None = None, value: str | None = None,
                          sensitive: bool = False) -> dict[str, Any]:
        # Sem ":" no rótulo: "- rótulo: valor" separa no primeiro ":".
        label = " ".join((label or "").strip().rstrip(":").replace(":", " -").split())
        if not label:
            raise VagasError("Informe 'label': o rótulo do campo como o formulário pede.")
        sensitive = sensitive or is_sensitive(label)
        value = value.strip() if value and value.strip() else None
        if sensitive and value is not None:
            raise VagasError(f"'{label}' é um dado sensível: o valor não é guardado. Chame sem 'value'; o campo fica "
                             f"como '{MANUAL}' e o usuário preenche no formulário.")
        perfil = _Profile(self.dir / "perfil.md")
        example = _Profile(self.dir / "perfil.example.md")
        wanted = section or OTHER_SECTION
        if perfil.section(wanted, create=False) is None and section is not None and section not in CREATABLE:
            names = ", ".join(name for _, name in perfil.sections())
            raise VagasError(f"Seção {section!r} não existe no perfil. Seções: {names}. Sem 'section', o campo vai "
                             f"para '{OTHER_SECTION}'.")

        result: dict[str, Any] = {"created": {"perfil": False, "example": False}, "updated": False}
        existing = perfil.find(label)
        if existing is not None:
            current = _ITEM.match(perfil.lines[existing])
            if value is not None and current["value"].strip().startswith("<"):
                perfil.lines[existing] = f"- {current['label']}: {value}"
                result["updated"] = True
            result["line"] = perfil.lines[existing]
            result["section"] = next((n for i, n in reversed(perfil.sections()) if i < existing), wanted)
        else:
            header, name = (perfil.section_before(wanted, OTHER_SECTION) if wanted in CREATABLE
                            else perfil.section(wanted, create=True))
            line = f"- {label}: {MANUAL if sensitive else value or PLACEHOLDER}"
            perfil.insert(header, line)
            result["created"]["perfil"] = True
            result["line"], result["section"] = line, name
        if example.find(label) is None:
            header, _ = (example.section_before(result["section"], OTHER_SECTION) if result["section"] in CREATABLE
                         else example.section(result["section"], create=True))
            example.insert(header, f"- {label}: {MANUAL if sensitive else '<...>'}")
            result["created"]["example"] = True
        if result["created"]["perfil"] or result["updated"]:
            perfil.save()
        if result["created"]["example"]:
            example.save()
        return result
