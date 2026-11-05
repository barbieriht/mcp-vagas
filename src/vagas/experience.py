"""Anos de experiência do usuário pelo currículo geral (períodos sobrepostos contam uma vez). Não depende de MCP."""

import re
from datetime import date
from typing import Any

from vagas.normalize import normalize_text

_MONTHS = {
    "jan": 1, "feb": 2, "fev": 2, "mar": 3, "apr": 4, "abr": 4, "may": 5, "mai": 5, "jun": 6, "jul": 7,
    "aug": 8, "ago": 8, "sep": 9, "set": 9, "oct": 10, "out": 10, "nov": 11, "dec": 12, "dez": 12,
}
_CURRENT = {"", "present", "presente", "atual", "current", "o momento", "hoje", "now"}


def _month(text: str | None, today: date, is_end: bool) -> int | None:
    """"May 2024", "mai 2024", "2024-05" ou "2024" -> índice do mês (ano * 12 + mês - 1)."""
    norm = normalize_text(text or "").rstrip(".")
    if is_end and norm in _CURRENT:
        return today.year * 12 + today.month - 1
    if match := re.fullmatch(r"([a-z]{3})[a-z]*\.?\s+(\d{4})", norm):
        month = _MONTHS.get(match[1])
        return int(match[2]) * 12 + month - 1 if month else None
    if match := re.fullmatch(r"(\d{4})-(\d{1,2})", norm):
        return int(match[1]) * 12 + int(match[2]) - 1
    if match := re.fullmatch(r"(\d{4})", norm):
        return int(match[1]) * 12 + (11 if is_end else 0)
    return None


def experience_years(resume: dict[str, Any], today: date) -> float | None:
    """Soma dos meses das experiências profissionais (mês de início e de fim inclusos), com uma casa decimal."""
    periods = []
    for item in resume.get("experience") or []:
        start, end = _month(item.get("start"), today, False), _month(item.get("end"), today, True)
        if start is not None and end is not None and end >= start:
            periods.append((start, end))
    if not periods:
        return None
    months, current = 0, None
    for start, end in sorted(periods):
        if current and start <= current[1] + 1:
            current = (current[0], max(current[1], end))
            continue
        if current:
            months += current[1] - current[0] + 1
        current = (start, end)
    months += current[1] - current[0] + 1
    return round(months / 12, 1)
