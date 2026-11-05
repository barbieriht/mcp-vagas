"""Renderização do currículo em PDF com Typst (template de uma coluna, amigável a ATS)."""

import io
import json
import re
import unicodedata
from importlib.resources import files
from pathlib import Path
from typing import Any

import pypdf
import typst

from vagas.repo import VagasError

MAX_PAGES = 2
MAX_LABEL_CHARS = 70  # parte do rótulo no nome do arquivo; cargos longos são cortados entre palavras


def default_output_dir(db_path: Path | str | None = None) -> Path | None:
    from vagas.config import resolve

    return resolve("resume_out", db_path)[0]


def render_resume(resume: dict[str, Any], out_dir: Path | str | None, label: str | None = None) -> dict[str, Any]:
    """Gera o PDF em out_dir sem sobrescrever arquivos; retorna {path, pages, warnings}."""
    if out_dir is None:
        raise VagasError(
            "Pasta de saída dos currículos não configurada. Chame get_config, pergunte ao usuário a pasta "
            "(sugerida em suggestions) e grave com set_config(resume_out). Alternativa: variável VAGAS_RESUME_OUT "
            "(ex.: /mnt/c/Users/<usuário>/Curriculos) na configuração do servidor MCP."
        )
    template = files("vagas").joinpath("templates/resume.typ").read_bytes()
    pdf = typst.compile(
        template,
        sys_inputs={"data": json.dumps(resume, ensure_ascii=False)},
        ignore_system_fonts=True,
    )
    pages = len(pypdf.PdfReader(io.BytesIO(pdf)).pages)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _free_path(out_dir, _file_stem(resume["basics"]["name"], label))
    path.write_bytes(pdf)

    warnings = []
    if pages > MAX_PAGES:
        warnings.append(f"O currículo tem {pages} páginas; o recomendado é no máximo {MAX_PAGES} páginas.")
    return {"path": str(path), "pages": pages, "warnings": warnings}


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "_".join(re.findall(r"[A-Za-z0-9]+", ascii_text))


def _file_stem(name: str, label: str | None) -> str:
    words = name.split()
    short = " ".join([words[0], words[-1]]) if len(words) > 1 else name
    parts = [_slug(short), "Resume"]
    if label and _slug(label):
        parts.append(_shorten(_slug(label)))
    return "_".join(parts)


def _shorten(slug: str) -> str:
    if len(slug) <= MAX_LABEL_CHARS:
        return slug
    return slug[:MAX_LABEL_CHARS + 1].rsplit("_", 1)[0]


def _free_path(out_dir: Path, stem: str) -> Path:
    path = out_dir / f"{stem}.pdf"
    n = 2
    while path.exists():
        path = out_dir / f"{stem}_{n}.pdf"
        n += 1
    return path
