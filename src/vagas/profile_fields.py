"""Campos de formulário no perfil da Skill (perfil.md, pessoal, e perfil.example.md, versionado). Não depende de MCP.

O perfil é Markdown: seções "## <nome>" com itens "- <rótulo>: <valor>". Um campo novo entra nos dois
arquivos, na mesma seção: no perfil com o valor (ou <PREENCHER>), no exemplo com <...>. Dados
sensíveis (documentos, senhas, dados bancários) nunca são guardados: ficam como "informar manualmente".
"""

import os
import re
from pathlib import Path
from typing import Any

from vagas.normalize import normalize_text
from vagas.repo import VagasError
from vagas.salary_policy import default_policy_path

OTHER_SECTION = "Outros campos de formulário"
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

    def insert(self, header: int, line: str) -> None:
        end = next((i for i in range(header + 1, len(self.lines)) if self.lines[i].startswith("## ")), len(self.lines))
        last = max((i for i in range(header, end) if self.lines[i].strip()), default=header)
        self.lines.insert(last + 1, line)


VAULT = "no cofre (extensão do Chrome)"
TALENT_POOL = "Incluir em bancos de talentos"


class ProfileFiles:
    def __init__(self, skill_dir: Path | str):
        self.dir = Path(skill_dir)

    def get_profile(self, vault_fields: list[str]) -> dict[str, Any]:
        """Perfil estruturado: seções e campos com status (ok, preencher, manual, cofre, cofre_vazio),
        subitens como observações. Campos do cofre nunca trazem o valor, só a indicação."""
        from vagas.sensitive import ALLOWED_FIELDS

        by_label = {_key(label): field for field, label in ALLOWED_FIELDS.items()}
        perfil = _Profile(self.dir / "perfil.md")
        sections: list[dict[str, Any]] = []
        to_fill: list[str] = []
        vault_missing: list[str] = []
        current = None
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
                if value.startswith("<"):
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
                current["notes"].append(line.strip()[2:].strip())
        return {"sections": sections, "to_fill": to_fill, "vault_missing": vault_missing}

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
        label = (label or "").strip().rstrip(":").strip()
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
        if perfil.section(wanted, create=False) is None and section is not None:
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
            header, name = perfil.section(wanted, create=True)
            line = f"- {label}: {MANUAL if sensitive else value or PLACEHOLDER}"
            perfil.insert(header, line)
            result["created"]["perfil"] = True
            result["line"], result["section"] = line, name
        if example.find(label) is None:
            header, _ = example.section(result["section"], create=True)
            example.insert(header, f"- {label}: {MANUAL if sensitive else '<...>'}")
            result["created"]["example"] = True
        if result["created"]["perfil"] or result["updated"]:
            perfil.save()
        if result["created"]["example"]:
            example.save()
        return result
