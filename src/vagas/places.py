"""Estados brasileiros e locais aceitos agrupados por estado. Usado pela triagem, pelas consultas e pelo painel.

Locais aceitos, numa linha só: grupos "UF: cidade, cidade" separados por ponto e vírgula, como
"SP: São Carlos, São Paulo, Barueri; RJ: Niterói; MG:". Um estado sem cidades vale como estado aceito
sem cidade aceita de antemão. Uma parte sem "UF:" (o formato antigo, "São Paulo, Campinas") são cidades
de qualquer estado.
"""

import re
from dataclasses import dataclass

from vagas.normalize import normalize_text
from vagas.repo import VagasError

STATES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}


def state_code(value: str) -> str | None:
    """Sigla ("sp", "São Paulo" -> "SP"), ou None se não for um estado."""
    norm = normalize_text(value)
    return next((uf for uf, name in STATES.items() if norm in (uf.lower(), normalize_text(name))), None)


def state_of(location: str | None) -> str | None:
    """UF do local da vaga ("Barueri, São Paulo, Brazil" -> SP), ou None se não der para saber."""
    if not location:
        return None
    parts = [re.sub(r"^Greater\s+|\s+Area$", "", p.strip()) for p in location.split(",")]
    return next((uf for part in reversed(parts) if (uf := state_code(part))), None)


@dataclass(frozen=True)
class PlaceGroup:
    state: str | None  # UF; None = cidades de qualquer estado (formato antigo)
    cities: tuple[str, ...]  # como escritas

    def accepts(self, city: str, state: str | None) -> bool:
        """A cidade (já normalizada) é uma das do grupo, no estado do grupo quando os dois são conhecidos."""
        if self.state and state and state != self.state:
            return False
        return any(re.search(rf"(?<!\w){re.escape(normalize_text(c))}(?!\w)", city) for c in self.cities)


def _clean(text: str) -> str:
    return text.strip().rstrip(".;").strip()


def parse_places(value: str, where: str = "locais aceitos") -> tuple[PlaceGroup, ...]:
    groups: list[PlaceGroup] = []
    for part in (p for p in value.split(";") if _clean(p)):
        state, cities = (None, part)
        if ":" in part:
            name, cities = part.split(":", 1)
            if (state := state_code(_clean(name))) is None:
                raise VagasError(f"Estado desconhecido em {where}: {_clean(name)!r}. Use a sigla (ex.: SP) ou o "
                                 "nome do estado antes dos dois-pontos, como 'SP: São Paulo, Campinas'.")
        if any(g.state == state for g in groups):
            label = state or "sem estado"
            raise VagasError(f"O estado {label} aparece duas vezes em {where}: junte as cidades num grupo só.")
        names = tuple(dict.fromkeys(c for c in (_clean(c) for c in cities.split(",")) if c))
        groups.append(PlaceGroup(state, names))
    return tuple(groups)


def format_places(groups: tuple[PlaceGroup, ...] | list[PlaceGroup]) -> str:
    """O inverso de parse_places: "SP: São Carlos, São Paulo; MG:"."""
    parts = []
    for group in groups:
        cities = ", ".join(group.cities)
        parts.append(f"{group.state}: {cities}".rstrip() if group.state else cities)
    return "; ".join(parts)
