"""Campos "- Rótulo: valor" dos arquivos pessoais em Markdown (perfil, critérios, política salarial).

Lê os itens por seção ("## Nome"), com subitens indentados, e para em "## Valores aceitos" (a
documentação do arquivo). `apply` troca só o valor das linhas pedidas e devolve o resto do texto
intacto: cabeçalho, explicações, tabelas, comentários e a grafia dos rótulos. Não depende de MCP.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from vagas.normalize import normalize_text

_ITEM = re.compile(r"^(?P<prefix>(?P<indent>[ \t]*)[-*][ \t]+)(?P<label>[^:\n]+?)[ \t]*:(?P<space>[ \t]*)(?P<value>.*?)[ \t]*$")
_BULLET = re.compile(r"^(?P<indent>[ \t]+)[-*][ \t]+(?P<text>.*?)[ \t]*$")
NOTE_LABELS = {"valores aceitos"}  # subitens que documentam o campo, não são campos


@dataclass
class Item:
    line: int
    label: str
    value: str
    section: str | None
    parent: str | None
    notes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return "/".join(part for part in (self.section, self.parent, self.label) if part)


def _key(field_id: str) -> str:
    return "/".join(" ".join(normalize_text(part).split()) for part in field_id.split("/"))


def parse(text: str) -> list[Item]:
    items: list[Item] = []
    section: str | None = None
    parent: Item | None = None
    for number, line in enumerate(text.splitlines()):
        if line.startswith("## "):
            section = line[3:].strip()
            if normalize_text(section).startswith("valores aceitos"):
                break
            parent = None
            continue
        match = _ITEM.match(line)
        nested = bool(match and match["indent"]) or bool(not match and _BULLET.match(line))
        if match and not nested:
            parent = Item(number, match["label"].strip(), match["value"], section, None)
            items.append(parent)
        elif match and parent is not None and normalize_text(match["label"]) not in NOTE_LABELS:
            items.append(Item(number, match["label"].strip(), match["value"], section, parent.label))
        elif nested and parent is not None:
            bullet = _BULLET.match(line)
            parent.notes.append(bullet["text"] if bullet else line.strip())
    return items


def apply(text: str, values: dict[str, str]) -> str:
    """Troca os valores pedidos ({id: valor}). KeyError para id desconhecido; ValueError para valor com
    quebra de linha (viraria outra linha do arquivo)."""
    by_key = {_key(item.id): item for item in parse(text)}
    lines = text.splitlines(keepends=True)
    for field_id, value in values.items():
        item = by_key.get(_key(field_id))
        if item is None:
            raise KeyError(field_id)
        if "\n" in value or "\r" in value:
            raise ValueError(f"{field_id}: o valor não pode ter quebra de linha.")
        original = lines[item.line]
        ending = original[len(original.rstrip("\r\n")):]
        match = _ITEM.match(original.rstrip("\r\n"))
        separator = " " if value else ""
        lines[item.line] = f"{match['prefix']}{match['label']}:{separator}{value.strip()}{ending}"
    return "".join(lines)


def write_atomic(path: Path | str, text: str) -> None:
    """Grava sem deixar o arquivo pela metade. Um symlink (o instalador liga os arquivos da Skill ao
    lado do banco) continua symlink: grava no arquivo para onde ele aponta."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, target)
