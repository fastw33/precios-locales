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

