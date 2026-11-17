"""Estados brasileiros: sigla a partir do nome ou do local de uma vaga. Usado pela triagem e pelas consultas."""

import re

from vagas.normalize import normalize_text

STATES = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia", "CE": "ceara",
    "DF": "distrito federal", "ES": "espirito santo", "GO": "goias", "MA": "maranhao", "MT": "mato grosso",
    "MS": "mato grosso do sul", "MG": "minas gerais", "PA": "para", "PB": "paraiba", "PR": "parana",
    "PE": "pernambuco", "PI": "piaui", "RJ": "rio de janeiro", "RN": "rio grande do norte",
    "RS": "rio grande do sul", "RO": "rondonia", "RR": "roraima", "SC": "santa catarina", "SP": "sao paulo",
    "SE": "sergipe", "TO": "tocantins",
}


def state_code(value: str) -> str | None:
    """Sigla ("sp", "São Paulo" -> "SP"), ou None se não for um estado."""
    norm = normalize_text(value)
    return next((uf for uf, name in STATES.items() if norm in (uf.lower(), name)), None)


def state_of(location: str | None) -> str | None:
    """UF do local da vaga ("Barueri, São Paulo, Brazil" -> SP), ou None se não der para saber."""
    if not location:
        return None
    parts = [re.sub(r"^Greater\s+|\s+Area$", "", p.strip()) for p in location.split(",")]
    return next((uf for part in reversed(parts) if (uf := state_code(part))), None)
