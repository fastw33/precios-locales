from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import Material, MaterialAlias, PriceHistory, ValidationSettings
from app.services.text_normalizer import normalize_for_exact_match, normalize_symbols_and_spaces


@dataclass
class RowValidation:
    material_raw: str
    material_normalized: str
    suggested_material_id: int | None
    approved_material_id: int | None
    match_type: str
    match_score: float | None
    requires_review: bool
    review_reason: str
    validation_status: str
    validation_notes: str | None


def get_or_create_validation_settings(db: Session, id_personal: int) -> ValidationSettings:
    settings = db.query(ValidationSettings).filter_by(id_personal=id_personal).one_or_none()
    if settings:
        return settings
    settings = ValidationSettings(id_personal=id_personal)
    db.add(settings)
    db.flush()
    return settings


def validate_material_and_price(
    db: Session,
    *,
    id_personal: int,
    section: str,
    row: dict,
    settings: ValidationSettings,
) -> RowValidation:
    material_raw = row.get("material") or row.get("material_raw") or ""
    material_normalized = normalize_for_exact_match(material_raw)
    symbol_key = normalize_symbols_and_spaces(material_raw)
    price_value = row.get("price_value")

    if row.get("requires_review") is True:
        return _review(material_raw, material_normalized, "no_match", None, "ocr_requires_review", "El OCR marcó la fila para revisión.")

    material_conf = row.get("material_confidence")
    if material_conf is not None and Decimal(str(material_conf)) < settings.min_material_confidence:
        return _review(material_raw, material_normalized, "no_match", None, "low_material_confidence", "Confianza baja en el material.")

    price_conf = row.get("price_confidence")
    if (
        price_conf is not None
        and Decimal(str(price_conf)) < settings.min_price_confidence
        and not row.get("price_autocorrected")
    ):
        return _review(material_raw, material_normalized, "no_match", None, "low_price_confidence", "Confianza baja en el precio.")

    if price_value is None:
        return _review(material_raw, material_normalized, "no_match", None, "invalid_price", "Precio inválido o no detectado.")

    alias = db.query(MaterialAlias).filter_by(id_personal=id_personal, section=section, normalized_alias=material_normalized).one_or_none()
    if alias:
        price_review = _validate_price_range(db, id_personal, alias.material_id, int(price_value), settings)
        if price_review:
            return _review_with_material(material_raw, material_normalized, alias.material_id, "exact_alias", 100, "price_out_of_range", price_review)
        return RowValidation(material_raw, material_normalized, alias.material_id, alias.material_id, "exact_alias", 100, False, "none", "valid", None)

    material = db.query(Material).filter_by(id_personal=id_personal, section=section, normalized_name=material_normalized, active=True).one_or_none()
    if material:
        price_review = _validate_price_range(db, id_personal, material.id, int(price_value), settings)
        if price_review:
            return _review_with_material(material_raw, material_normalized, material.id, "exact_material", 100, "price_out_of_range", price_review)
        return RowValidation(material_raw, material_normalized, material.id, material.id, "exact_material", 100, False, "none", "valid", None)

    symbol_match = _find_symbol_space_match(db, id_personal, section, symbol_key)
    if symbol_match and settings.allow_symbol_space_autocorrect:
        price_review = _validate_price_range(db, id_personal, symbol_match.id, int(price_value), settings)
        if price_review:
            return _review_with_material(material_raw, material_normalized, symbol_match.id, "symbol_space_variant", 100, "price_out_of_range", price_review)
        return RowValidation(
            material_raw,
            material_normalized,
            symbol_match.id,
            symbol_match.id,
            "symbol_space_variant",
            100,
            False,
            "none",
            "auto_corrected",
            f"Autocorregido contra material existente: {symbol_match.canonical_name}",
        )

    possible = _find_possible_text_change(db, id_personal, section, material_normalized)
    if possible:
        material, score = possible
        return _review_with_material(
            material_raw,
            material_normalized,
            material.id,
            "possible_text_change",
            round(score * 100, 2),
            "text_changed",
            f"Posible cambio de texto/letra. Sugerido: {material.canonical_name}",
        )

    return _review(material_raw, material_normalized, "new_material", None, "new_material", "Material nuevo. Debe ser validado por el usuario.")


def _find_symbol_space_match(db: Session, id_personal: int, section: str, symbol_key: str) -> Material | None:
    materials = db.query(Material).filter_by(id_personal=id_personal, section=section, active=True).all()
    for material in materials:
        if normalize_symbols_and_spaces(material.canonical_name) == symbol_key:
            return material
    aliases = db.query(MaterialAlias).filter_by(id_personal=id_personal, section=section).all()
    for alias in aliases:
        if normalize_symbols_and_spaces(alias.alias_text) == symbol_key:
            return alias.material
    return None


def _find_possible_text_change(db: Session, id_personal: int, section: str, normalized: str) -> tuple[Material, float] | None:
    best: tuple[Material, float] | None = None
    for material in db.query(Material).filter_by(id_personal=id_personal, section=section, active=True).all():
        score = SequenceMatcher(None, normalized, material.normalized_name).ratio()
        if score >= 0.86 and (best is None or score > best[1]):
            best = (material, score)
    return best


def _validate_price_range(db: Session, id_personal: int, material_id: int, new_price: int, settings: ValidationSettings) -> str | None:
    latest = (
        db.query(PriceHistory)
        .filter_by(id_personal=id_personal, material_id=material_id)
        .order_by(desc(PriceHistory.observed_date), desc(PriceHistory.id))
        .first()
    )
    if not latest or latest.price_value == 0:
        return None
    change_percent = abs(new_price - latest.price_value) / latest.price_value * 100
    if Decimal(str(change_percent)) > settings.max_auto_price_change_percent:
        return f"Precio fuera de rango: cambio {change_percent:.2f}% contra último valor {latest.price_value}."
    return None


def _review(material_raw: str, material_normalized: str, match_type: str, match_score: float | None, reason: str, notes: str) -> RowValidation:
    return RowValidation(material_raw, material_normalized, None, None, match_type, match_score, True, reason, "pending_review", notes)


def _review_with_material(
    material_raw: str,
    material_normalized: str,
    material_id: int,
    match_type: str,
    match_score: float | None,
    reason: str,
    notes: str,
) -> RowValidation:
    return RowValidation(material_raw, material_normalized, material_id, None, match_type, match_score, True, reason, "pending_review", notes)
