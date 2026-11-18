"""Política salarial pessoal (politica-salarial.md) lida por código. Não depende de MCP.

Formato (lista em Markdown; linhas fora deste formato são ignoradas):

    - Modo: minimo                      (ou "faixa"; padrão minimo)
    - Multiplicador PJ: 1.4

    - Faixa: mínimo 8.000, máximo 12.000
      - Tipos: remoto
      - Remoto: nacional
      - CLT: sim
    - Faixa: mínimo 3000
      - Tipos: remoto
      - Remoto: internacional
      - Moeda: USD
    - Faixa: mínimo 10.500
      - Tipos: híbrido, presencial
      - Locais: SP: São Paulo, Campinas, demais cidades; RJ: demais cidades
      - CLT: sim

Cada faixa é um conjunto de vagas com um valor mensal. Remoto nacional é vaga paga em BRL; remoto
internacional, em USD ou EUR (a faixa diz qual em "Moeda"). Híbrido e presencial valem nas cidades de
"Locais" (no formato dos locais aceitos: "UF: cidade, cidade"), e "demais cidades" vale para as outras
cidades do estado. A mesma cidade na mesma modalidade só pode estar numa faixa. "CLT: sim" marca a faixa
em CLT, multiplicada pelo multiplicador PJ em vagas PJ.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from vagas.db import default_db_path
from vagas.models import CURRENCIES, SALARY_MODES, WORK_MODES
from vagas.normalize import normalize_text
from vagas.places import PlaceGroup, parse_places, state_of
from vagas.repo import VagasError

_ITEM = re.compile(r"^(?P<indent>\s*)[-*]\s+(?P<key>[^:]+?)\s*:\s*(?P<value>.*?)\s*$")
_OLD_BAND = re.compile(r"\((?:[^)]*\b(?:BRL|USD|EUR)\b[^)]*)\)$", re.I)  # "Remoto nacional (BRL, CLT)"
_NUMBER = r"\d[\d.,]*"
_MIN = re.compile(rf"m[ií]nimo\s*(?:de\s*)?(?:R?\$\s*)?(?P<n>{_NUMBER})", re.I)
_MAX = re.compile(rf"m[aá]ximo\s*(?:de\s*)?(?:R?\$\s*)?(?P<n>{_NUMBER})", re.I)
_ALIAS = re.compile(r"usar a faixa d[oa]s?\s+(?P<target>.+?)\.?$", re.I)  # formato antigo (só o painel lê)
_MODES = {"remoto": "remoto", "hibrido": "hibrido", "presencial": "presencial"}
MODE_TITLES = {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial"}
SCOPES = ("nacional", "internacional")
FOREIGN = tuple(c for c in CURRENCIES if c != "BRL")
REST = "demais cidades"  # nos Locais: as cidades do estado sem faixa própria


@dataclass(frozen=True)
class Band:
    modes: frozenset[str]
    scope: str | None  # "nacional" ou "internacional", quando a faixa tem remoto
    places: tuple[PlaceGroup, ...]  # cidades por estado, na ordem do arquivo (sem "demais cidades")
    rest: tuple[str, ...]  # UFs com "demais cidades"
    currency: str
    clt: bool
    min: float
    max: float | None
    line: int = 0

    @property
    def label(self) -> str:
        return band_label(self.modes, self.scope, self.places, self.rest)

    def as_dict(self) -> dict:
        return {"label": self.label, "currency": self.currency, "clt": self.clt, "min": self.min, "max": self.max}

    def accepts(self, city: str, state: str | None) -> bool:
        return any(group.accepts(city, state) for group in self.places)


def band_label(modes, scope: str | None, places, rest) -> str:
    """"Remoto nacional", "Híbrido/presencial em São Carlos, demais cidades de SP" e combinações."""
    parts = []
    if "remoto" in modes:
        parts.append(f"Remoto {scope}" if scope else "Remoto")
    local = [MODE_TITLES[m] for m in ("hibrido", "presencial") if m in modes]
    if local:
        where = _where(places, rest)
        text = "/".join([local[0]] + [m.lower() for m in local[1:]])
        parts.append(f"{text} em {', '.join(where)}" if where else text)
    if len(parts) == 2:
        return f"{parts[0]} e {parts[1][0].lower()}{parts[1][1:]}"
    return parts[0] if parts else "Faixa"


def _where(places, rest) -> list[str]:
    """Locais na ordem dos estados: as cidades de cada um e, depois, "demais cidades de UF"."""
    states = list(dict.fromkeys([g.state for g in places] + list(rest)))
    where = []
    for uf in states:
        where += [c for g in places if g.state == uf for c in g.cities]
        if uf in rest:
            where.append(f"demais cidades de {uf}")
    return where


@dataclass(frozen=True)
class SalaryPolicy:
    mode: str
    pj_multiplier: float | None
    bands: tuple[Band, ...]

    def band_for(self, work_mode: str, location: str | None, currency: str) -> Band:
        """Faixa da modalidade, do local e da moeda da vaga."""
        if work_mode not in WORK_MODES:
            raise VagasError(f"'work_mode' inválido: {work_mode!r}. Use um de: {', '.join(WORK_MODES)}.")
        if work_mode == "remoto":
            scope = "nacional" if currency == "BRL" else "internacional"
            hit = next((b for b in self.bands if "remoto" in b.modes and b.scope == scope
                        and b.currency == currency), None)
            if hit is None:
                raise VagasError(f"A política salarial não tem faixa para vaga remota {scope} em {currency}. "
                                 "Acrescente uma no painel ou informe my_min/my_max.")
            return hit
        if currency != "BRL":
            raise VagasError(f"A política salarial não tem faixa para vaga {work_mode} em {currency}: as faixas de "
                             "híbrido e presencial são em BRL. Informe my_min/my_max.")
        if not location:
            raise VagasError(f"Vaga {work_mode} sem local informado: confira o local da vaga ou informe my_min/my_max.")
        # Só a cidade (1ª parte do local): em "Campinas, São Paulo", "São Paulo" é o estado.
        city = re.sub(r"^greater\s+|\s+area$", "", normalize_text(re.split(r",|\s+-\s+", location)[0]))
        state = state_of(location)
        candidates = [b for b in self.bands if work_mode in b.modes]
        hit = (next((b for b in candidates if b.accepts(city, state)), None)
               or next((b for b in candidates if state and state in b.rest), None))
        if hit is None:
            raise VagasError(f"A política salarial não cobre o local {location!r} para vaga {work_mode}. Acrescente "
                             "a cidade (ou \"demais cidades\" do estado) numa faixa no painel, ou informe my_min/my_max.")
        return hit


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


def _clean(text: str) -> str:
    return text.strip().rstrip(".;").strip()


def _words(value: str) -> list[str]:
    return [normalize_text(_clean(v)) for v in value.split(",") if _clean(v)]


def _band(number: int, value: str, subs: dict[str, tuple[int, str]], source: str) -> Band:
    """Uma faixa: a linha "- Faixa: mínimo ..." e os subitens (chave normalizada -> (linha, valor))."""
    where = f"{source}, linha {number}"
    lo, hi = _MIN.search(value), _MAX.search(value)
    if not lo:
        raise VagasError(f"{where}: faixa sem 'mínimo' (ex.: '- Faixa: mínimo 8000, máximo 12000').")
    lo_value = parse_number(lo["n"])
    hi_value = parse_number(hi["n"]) if hi else None
    if hi_value is not None and hi_value < lo_value:
        raise VagasError(f"{where}: 'máximo' menor que 'mínimo'.")
    if "tipos" not in subs:
        raise VagasError(f"{where}: faixa sem 'Tipos' (remoto, híbrido, presencial).")
    modes = []
    for word in _words(subs["tipos"][1]):
        if word not in _MODES:
            raise VagasError(f"{where}: tipo de vaga desconhecido: {word!r}. Use remoto, híbrido ou presencial.")
        modes.append(_MODES[word])
    if not modes:
        raise VagasError(f"{where}: marque ao menos um tipo de vaga (remoto, híbrido, presencial).")
    scope, currency = None, "BRL"
    if "remoto" in modes:
        scopes = _words(subs.get("remoto", (0, ""))[1])
        if not scopes:
            raise VagasError(f"{where}: faixa com remoto precisa de 'Remoto: nacional' ou 'Remoto: internacional'.")
        if any(s not in SCOPES for s in scopes):
            raise VagasError(f"{where}: 'Remoto' aceita nacional ou internacional.")
        if len(set(scopes)) > 1:
            raise VagasError(f"{where}: nacional e internacional não ficam na mesma faixa: um valor só não serve "
                             "a duas moedas (nacional é BRL; internacional, USD ou EUR). Crie uma faixa para cada.")
        scope = scopes[0]
    local = [m for m in modes if m != "remoto"]
    if scope == "internacional":
        if local:
            raise VagasError(f"{where}: remoto internacional (em USD ou EUR) não fica na mesma faixa que híbrido "
                             "ou presencial (em BRL). Crie uma faixa para cada.")
        currency = subs.get("moeda", (0, ""))[1].strip().rstrip(".").upper()
        if currency not in FOREIGN:
            raise VagasError(f"{where}: remoto internacional precisa de 'Moeda: USD' ou 'Moeda: EUR'.")
    places: list[PlaceGroup] = []
    rest: list[str] = []
    if local:
        if "locais" not in subs or not _clean(subs["locais"][1]):
            raise VagasError(f"{where}: faixa de híbrido ou presencial precisa de 'Locais' (ex.: "
                             "'SP: São Carlos, demais cidades').")
        for group in parse_places(_clean(subs["locais"][1]), f"{source}, linha {subs['locais'][0]}"):
            cities = tuple(c for c in group.cities if normalize_text(c) != REST)
            if len(cities) < len(group.cities):
                if group.state is None:
                    raise VagasError(f"{where}: \"demais cidades\" precisa do estado, como 'SP: demais cidades'.")
                rest.append(group.state)
            if cities or group.state:  # estado só com "demais cidades" fica, para a ordem dos locais
                places.append(PlaceGroup(group.state, cities))
    clt = normalize_text(_clean(subs.get("clt", (0, ""))[1])) in ("sim", "s", "yes", "true")
    return Band(frozenset(modes), scope, tuple(places), tuple(rest), currency, clt, lo_value, hi_value, number)


def _coverage(band: Band) -> list[tuple[tuple, str]]:
    """O que a faixa cobre, para achar o mesmo local na mesma modalidade em duas faixas."""
    keys = []
    if band.scope:
        keys.append((("remoto", band.scope, band.currency), f"remoto {band.scope} em {band.currency}"))
    for mode in sorted(band.modes - {"remoto"}):
        for group in band.places:
            for city in group.cities:
                name = f"{city}/{group.state}" if group.state else city
                keys.append(((mode, group.state, normalize_text(city)), f"{name} ({MODE_TITLES[mode].lower()})"))
        for uf in band.rest:
            keys.append(((mode, uf, REST), f"demais cidades de {uf} ({MODE_TITLES[mode].lower()})"))
    return keys


@dataclass
class BandBlock:
    """Um item "- Faixa: ..." no texto: linhas [start, end) (0-based, com os subitens), valor e subitens
    (chave normalizada -> (linha 1-based, valor))."""
    start: int
    end: int
    value: str
    subs: dict[str, tuple[int, str]]


def band_blocks(text: str) -> list[BandBlock]:
    """Os itens de faixa do texto, sem validar nada (o painel lê e regrava estes blocos)."""
    blocks: list[BandBlock] = []
    current: BandBlock | None = None
    for index, line in enumerate(text.splitlines()):
        if line.startswith("## Valores aceitos"):
            break
        item = _ITEM.match(line)
        nested = bool(line[:1] in (" ", "\t") and line.strip())
        if current is not None and nested:
            if item:
                current.subs[normalize_text(item["key"])] = (index + 1, item["value"])
            current.end = index + 1
            continue
        current = None
        if item and not item["indent"] and normalize_text(item["key"]) == "faixa":
            current = BandBlock(index, index + 1, item["value"], {})
            blocks.append(current)
    return blocks


def parse_policy(text: str, source: str = "politica-salarial.md") -> SalaryPolicy:
    mode, multiplier = "minimo", None

    for number, line in enumerate(text.splitlines(), start=1):
        where = f"{source}, linha {number}"
        if line.startswith("## Valores aceitos"):
            break  # documentação dos campos, não política
        if "<PREENCHER" in line:
            raise VagasError(f"Preencha o campo em {where}: {line.strip()}")
        item = _ITEM.match(line)
        if not item or item["indent"] or not item["value"].strip(" .;"):
            continue  # campo vazio vale o padrão, como sem a linha
        key, value = item["key"], item["value"]
        norm_key = normalize_text(key)
        if norm_key == "modo":
            words = normalize_text(value).strip(" .;").split()
            mode = words[0].rstrip(".;") if words else ""
            if mode not in SALARY_MODES:
                raise VagasError(f"'Modo' inválido em {where}: {value!r}. Valores aceitos: "
                                 f"{', '.join(SALARY_MODES)}.")
        elif norm_key == "multiplicador pj":
            try:
                multiplier = parse_number(value)
            except VagasError:
                raise VagasError(f"'Multiplicador PJ' inválido em {where}: {value!r} (ex.: 1.4).") from None
            if multiplier <= 0:
                raise VagasError(f"'Multiplicador PJ' deve ser maior que zero ({where}).")
        elif _OLD_BAND.search(key.strip()):
            raise VagasError(f"{where}: faixa no formato antigo ({line.strip()}). Abra o painel de configuração "
                             "e salve a política salarial para converter, ou reescreva no formato do "
                             "politica-salarial.example.md.")

    bands = [_band(block.start + 1, block.value, block.subs, source) for block in band_blocks(text)]
    if not bands:
        raise VagasError(f"{source}: nenhuma faixa encontrada. Use itens como '- Faixa: mínimo 8000' com os "
                         "subitens 'Tipos', 'Remoto' ou 'Locais' (modelo: politica-salarial.example.md).")
    seen: dict[tuple, int] = {}
    for band in bands:
        for key, text_key in _coverage(band):
            if key in seen:
                raise VagasError(f"{source}: {text_key} aparece em duas faixas (linha {seen[key]} e linha "
                                 f"{band.line}). Cada local, numa modalidade, tem um valor só.")
            seen[key] = band.line
    return SalaryPolicy(mode, multiplier, tuple(bands))
