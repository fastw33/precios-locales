from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import OcrDocument, OcrDocumentRow, PriceHistory
from app.services.date_parser import extract_detected_date
from app.services.validation_service import get_or_create_validation_settings, validate_material_and_price


def persist_ocr_result(
    db: Session,
    *,
    id_personal: int,
    ocr_result: dict,
    original_filename: str | None,
    original_image_size: int,
    compressed_image: dict,
    image_sha256: str,
    observed_date: date | None = None,
) -> tuple[OcrDocument, list[OcrDocumentRow]]:
    settings = get_or_create_validation_settings(db, id_personal)
    detected_date = observed_date or extract_detected_date(ocr_result)
    if detected_date is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "observed_date_required",
                "message": "No fue posible detectar la fecha de la lista. Ingresa la fecha visible en la imagen.",
            },
        )
    all_ocr_rows = [
        row
        for row in list(ocr_result.get("exportacion") or []) + list(ocr_result.get("nacional") or [])
        if not _is_section_header_row(row)
    ]

    existing_same_date = (
        db.query(OcrDocument)
        .filter(
            OcrDocument.id_personal == id_personal,
            OcrDocument.detected_date == detected_date,
            OcrDocument.status.in_(["pending_review", "processed"]),
        )
        .order_by(OcrDocument.id.desc())
        .first()
    )
    if existing_same_date:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Ya existe una lista de precios cargada para esta fecha.",
                "document_id": existing_same_date.id,
                "status": existing_same_date.status,
                "detected_date": detected_date.isoformat(),
            },
        )

    document = OcrDocument(
        id_personal=id_personal,
        status="pending_review",
        engine=ocr_result.get("engine") or "unknown",
        template=ocr_result.get("template"),
        detected_date=detected_date,
        original_filename=original_filename,
        compressed_image_path=compressed_image["path"],
        compressed_image_mime=compressed_image["mime"],
        compressed_image_size=compressed_image["size"],
        original_image_size=original_image_size,
        image_sha256=image_sha256,
        raw_ocr_json=ocr_result,
        template_compatible=(ocr_result.get("image_info") or {}).get("template_compatible"),
        total_rows=len(all_ocr_rows),
        rows_requiring_review=0,
        prices_detected=(ocr_result.get("summary") or {}).get("prices_detected") or 0,
    )
    db.add(document)
    db.flush()

    rows: list[OcrDocumentRow] = []
    rows_requiring_review = 0
    for raw_row in all_ocr_rows:
        section = _normalize_section(raw_row.get("section"))
        validation = validate_material_and_price(
            db,
            id_personal=id_personal,
            section=section,
            row=raw_row,
            settings=settings,
        )
        if validation.requires_review:
            rows_requiring_review += 1

        row = OcrDocumentRow(
            document_id=document.id,
            id_personal=id_personal,
            section=section,
            row_number=int(raw_row.get("row") or 0),
            material_raw=raw_row.get("material_raw") or raw_row.get("material"),
            material_ocr=raw_row.get("material"),
            material_normalized=validation.material_normalized,
            suggested_material_id=validation.suggested_material_id,
            approved_material_id=validation.approved_material_id,
            price_text=raw_row.get("price_text"),
            price_value=raw_row.get("price_value"),
            approved_price_value=None,
            material_confidence=raw_row.get("material_confidence"),
            price_confidence=raw_row.get("price_confidence"),
            match_type=validation.match_type,
            match_score=validation.match_score,
            requires_review=validation.requires_review,
            review_reason=validation.review_reason,
            validation_status=validation.validation_status,
            validation_notes=validation.validation_notes,
        )
        db.add(row)
        rows.append(row)

    db.flush()
    document.rows_requiring_review = rows_requiring_review

    if rows_requiring_review == 0:
        document.status = "processed"
        document.processed_at = datetime.utcnow()
        for row in rows:
            db.add(
                PriceHistory(
                    document_id=document.id,
                    document_row_id=row.id,
                    id_personal=id_personal,
                    material_id=row.approved_material_id,
                    observed_date=detected_date,
                    section=row.section,
                    price_value=row.price_value,
                    price_text=row.price_text,
                    source="ocr",
                )
            )

    db.flush()
    return document, rows


def _normalize_section(value: str | None) -> str:
    if value in {"EXPORTACION", "NACIONAL"}:
        return value
    return "OTRO"


def _is_section_header_row(row: dict) -> bool:
    material = (row.get("material") or row.get("material_raw") or "").strip().upper()
    material = material.translate(str.maketrans("ÁÉÍÓÚ", "AEIOU"))
    material = " ".join(material.split())
    return material in {"EXPORTACION", "IMPORTACION", "NACIONAL"}
