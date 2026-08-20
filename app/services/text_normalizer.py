from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = text.replace("|", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_for_exact_match(value: str | None) -> str:
    text = normalize_text(value)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_symbols_and_spaces(value: str | None) -> str:
    text = normalize_text(value)
    return re.sub(r"[^A-Z0-9]", "", text)


def is_section_header_material(value: str | None) -> bool:
    normalized = normalize_for_exact_match(value)
    if not normalized:
        return False

    tokens = normalized.split()
    if tokens[0] not in {"EXPORTACION", "IMPORTACION", "NACIONAL"}:
        return False
    return len(tokens) == 1 or all(token.isdigit() for token in tokens[1:])


def canonicalize_ocr_material(value: str | None) -> str:
    text = normalize_text(value)
    normalized = normalize_for_exact_match(text)

    if re.search(r"\bCH ACERO\b.*\bRESISTENCIA\b.*\bELECTRICA\b", normalized):
        return "CH. ACERO RESISTENCIA ELECTRICA"

    return text
