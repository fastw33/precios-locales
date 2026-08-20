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
    metadata = ocr_result.get("metadata") or {}
    date_address = metadata.get("date_address")
    if isinstance(date_address, dict):
        parsed = parse_spanish_date(date_address.get("text") or "")
        if parsed:
            return parsed

    candidates = []
    raw_full = ocr_result.get("raw_full_ocr") or {}
    if isinstance(raw_full, dict):
        candidates.append(raw_full.get("text") or "")
    candidates.append(ocr_result.get("standardized_text") or "")

    for text in candidates:
        parsed = parse_price_list_date(text)
        if parsed:
            return parsed
    return None


def parse_price_list_date(text: str) -> date | None:
    value = _normalize_date_text(text)
    fecha_match = re.search(r"\bFECHA\b\s*[:\-]?\s*(.{0,80})", value)
    if fecha_match:
        parsed = parse_spanish_date(fecha_match.group(1))
        if parsed:
            return parsed
    return None


def parse_spanish_date(text: str) -> date | None:
    value = _normalize_date_text(text)
    pattern = r"(\d{1,2})\s*(?:DE)?\s*([A-ZÁÉÍÓÚÑ]+)\s*(?:DE)?\s*(\d{4})"
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


def _normalize_date_text(text: str) -> str:
    value = (text or "").upper()
    value = value.replace("DEJULIO", "DE JULIO")
    value = value.replace("DEAGOSTO", "DE AGOSTO")
    value = value.replace("AGOSTQ", "AGOSTO")
    value = value.replace("AG0STO", "AGOSTO")
    value = re.sub(r"\s+", " ", value)
    return value.strip()
