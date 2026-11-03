"""Política salarial pessoal (politica-salarial.md) lida por código. Não depende de MCP.

Formato (lista em Markdown; linhas fora deste formato são ignoradas):

    - Modo: minimo                      (ou "faixa"; padrão minimo)
    - Multiplicador PJ: 1.4
    - Remoto nacional (BRL, CLT): mínimo 8.000, máximo 12.000
    - Híbrido/presencial em São Paulo e região (BRL, CLT): mínimo 10.500
    - Híbrido/presencial em São Carlos e região (BRL, CLT): usar a faixa do remoto nacional
    - Internacional (USD): mínimo 3000

Cada faixa vale para as modalidades citadas no rótulo (remoto, híbrido, presencial; nenhuma =
todas), para a cidade depois de "em" (nenhuma = qualquer local) e para a moeda entre parênteses.
"CLT" entre parênteses indica faixa em CLT, multiplicada pelo multiplicador PJ em vagas PJ.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from vagas.db import default_db_path
from vagas.models import CURRENCIES, SALARY_MODES, WORK_MODES
from vagas.normalize import normalize_text
from vagas.repo import VagasError

_ITEM = re.compile(r"^\s{0,1}[-*]\s+(?P<key>[^:]+?)\s*:\s*(?P<value>.+?)\s*$")
_BAND_KEY = re.compile(r"^(?P<label>.+?)\s*\((?P<tags>[^)]*)\)$")
_NUMBER = r"\d[\d.,]*"
_MIN = re.compile(rf"m[ií]nimo\s*(?:de\s*)?(?:R?\$\s*)?(?P<n>{_NUMBER})", re.I)
_MAX = re.compile(rf"m[aá]ximo\s*(?:de\s*)?(?:R?\$\s*)?(?P<n>{_NUMBER})", re.I)
_ALIAS = re.compile(r"usar a faixa d[oa]s?\s+(?P<target>.+?)\.?$", re.I)
_CITY = re.compile(r"\bem\s+(?P<city>.+?)(?:\s+e\s+regiao)?$")
_MODE_WORDS = {"remoto": "remoto", "hibrido": "hibrido", "presencial": "presencial"}


@dataclass(frozen=True)
class Band:
    label: str
    modes: frozenset[str]
    cities: tuple[str, ...]  # normalizadas; vazio = qualquer local
    currency: str
    clt: bool
    min: float
    max: float | None

    def as_dict(self) -> dict:
        return {"label": self.label, "currency": self.currency, "clt": self.clt, "min": self.min, "max": self.max}


@dataclass(frozen=True)
class SalaryPolicy:
    mode: str
    pj_multiplier: float | None
    bands: tuple[Band, ...]

    def band_for(self, work_mode: str, location: str | None, currency: str) -> Band:
        """Faixa da modalidade, do local e da moeda da vaga; prefere a faixa da cidade à genérica."""
        if work_mode not in WORK_MODES:
            raise VagasError(f"'work_mode' inválido: {work_mode!r}. Use um de: {', '.join(WORK_MODES)}.")
        candidates = [b for b in self.bands if b.currency == currency and work_mode in b.modes]
        if not candidates:
            raise VagasError(f"A política salarial não tem faixa para vaga {work_mode} em {currency}. "
                             "Acrescente uma ao politica-salarial.md ou informe my_min/my_max.")
        # Só a cidade (1ª parte do local): em "Campinas, São Paulo", "São Paulo" é o estado.
        city = re.sub(r"^greater\s+|\s+area$", "", normalize_text(re.split(r",|\s+-\s+", location or "")[0]))
        hit = next((b for b in candidates if city in b.cities), None)
        if hit:
            return hit
        generic = [b for b in candidates if not b.cities]
        if generic:
            return generic[0]
        cities = ", ".join(b.label for b in candidates)
        where = f"o local {location!r}" if location else "vaga sem local informado"
        raise VagasError(f"A política salarial não cobre {where} para vaga {work_mode} (faixas: {cities}). "
                         "Confira o local da vaga ou informe my_min/my_max.")


def default_policy_path(db_path: Path | str | None = None) -> Path:
    if env := os.environ.get("VAGAS_SALARY_POLICY"):
        return Path(env)
    db = Path(db_path) if db_path is not None else default_db_path()
    return db.parent / "politica-salarial.md"


def load_policy(path: Path | str) -> SalaryPolicy:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise VagasError(
            f"Política salarial não encontrada em {path}. Crie o arquivo ou aponte VAGAS_SALARY_POLICY "
            "para ele (modelo: skill/candidaturas/politica-salarial.example.md), ou informe my_min/my_max."
        ) from None
    return parse_policy(text, source=path.name)


def parse_number(text: str) -> float:
    """"8.000" e "8000" -> 8000; "10.500,50" -> 10500.5; "1.4" e "1,4" -> 1.4."""
    text = text.strip().rstrip(".,")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        raise VagasError(f"Número inválido na política salarial: {text!r}.") from None


def parse_policy(text: str, source: str = "politica-salarial.md") -> SalaryPolicy:
    mode, multiplier = "minimo", None
    bands: list[Band] = []
    aliases: list[tuple[int, str, frozenset[str], str | None, str, bool, str]] = []

    for number, line in enumerate(text.splitlines(), start=1):
        where = f"{source}, linha {number}"
        if line.startswith("## Valores aceitos"):
            break  # documentação dos campos, não política
        if "<PREENCHER" in line:
            raise VagasError(f"Preencha o campo em {where}: {line.strip()}")
        item = _ITEM.match(line)
        if not item:
            continue
        key, value = item["key"], item["value"]
        norm_key = normalize_text(key)
        if norm_key == "modo":
            words = normalize_text(value).strip(" .;").split()
            mode = words[0].rstrip(".;") if words else ""
            if mode not in SALARY_MODES:
                raise VagasError(f"'Modo' inválido em {where}: {value!r}. Valores aceitos: "
                                 f"{', '.join(SALARY_MODES)}.")
            continue
        if norm_key == "multiplicador pj":
            try:
                multiplier = parse_number(value)
            except VagasError:
                raise VagasError(f"'Multiplicador PJ' inválido em {where}: {value!r} (ex.: 1.4).") from None
            if multiplier <= 0:
                raise VagasError(f"'Multiplicador PJ' deve ser maior que zero ({where}).")
            continue
        band_key = _BAND_KEY.match(key)
        if not band_key:
            continue
        tags = [t.strip().upper() for t in band_key["tags"].split(",")]
        currency = next((t for t in tags if t in CURRENCIES), None)
        if currency is None:
            continue
        label = band_key["label"].strip()
        norm_label = normalize_text(label)
        modes = frozenset(m for word, m in _MODE_WORDS.items() if word in norm_label) or frozenset(WORK_MODES)
        city = _CITY.search(norm_label)
        cities = tuple(c.strip() for c in re.split(r",\s*|\s+e\s+", city["city"]) if c.strip()) if city else ()
        clt = "CLT" in tags

        if alias := _ALIAS.search(value):
            aliases.append((number, label, modes, cities, currency, clt, normalize_text(alias["target"])))
            continue
        lo, hi = _MIN.search(value), _MAX.search(value)
        if not lo:
            raise VagasError(f"Faixa sem 'mínimo' em {where}: {line.strip()}")
        lo_value = parse_number(lo["n"])
        hi_value = parse_number(hi["n"]) if hi else None
        if hi_value is not None and hi_value < lo_value:
            raise VagasError(f"'máximo' menor que 'mínimo' em {where}: {line.strip()}")
        bands.append(Band(label, modes, cities, currency, clt, lo_value, hi_value))

    for number, label, modes, cities, currency, clt, target in aliases:
        match = next((b for b in bands if normalize_text(b.label).startswith(target)
                      or target.startswith(normalize_text(b.label))), None)
        if match is None:
            raise VagasError(f"{source}, linha {number}: faixa {target!r} citada em 'usar a faixa' não existe.")
        bands.append(Band(label, modes, cities, currency, clt, match.min, match.max))

    if not bands:
        raise VagasError(f"{source}: nenhuma faixa encontrada. Use linhas como "
                         "'- Remoto nacional (BRL, CLT): mínimo 8.000, máximo 12.000'.")
    return SalaryPolicy(mode, multiplier, tuple(bands))
