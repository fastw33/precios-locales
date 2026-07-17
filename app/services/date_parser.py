from __future__ import annotations

import re
from datetime import date


MONTHS_ES = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}


def extract_detected_date(ocr_result: dict) -> date | None:
    candidates = []
    metadata = ocr_result.get("metadata") or {}
    for key in ("date_address", "validity"):
        value = metadata.get(key)
        if isinstance(value, dict):
            candidates.append(value.get("text") or "")
    candidates.append(ocr_result.get("standardized_text") or "")

    for text in candidates:
        parsed = parse_spanish_date(text)
        if parsed:
            return parsed
    return None


def parse_spanish_date(text: str) -> date | None:
    value = text.upper().replace("DEJULIO", "DE JULIO")
    pattern = r"(\d{1,2})\s*(?:DE)?\s*([A-ZÁÉÍÓÚÑ]+)\s*(\d{4})"
    for day_raw, month_raw, year_raw in re.findall(pattern, value):
        month = MONTHS_ES.get(_strip_accents(month_raw))
        if not month:
            continue
        try:
            return date(int(year_raw), month, int(day_raw))
        except ValueError:
            continue
    return None


def _strip_accents(value: str) -> str:
    return value.translate(str.maketrans("ÁÉÍÓÚ", "AEIOU"))

