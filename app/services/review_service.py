from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Material, MaterialAlias, OcrDocument, OcrDocumentRow, OcrReviewEvent, PriceHistory
from app.schemas.ocr import ReviewDocumentIn, ReviewRowIn
from app.services.text_normalizer import normalize_for_exact_match


def review_document(db: Session, document_id: int, payload: ReviewDocumentIn) -> OcrDocument:
    document = db.query(OcrDocument).filter_by(id=document_id).one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    if document.status != "pending_review":
        raise HTTPException(status_code=409, detail="El documento no está pendiente de revisión.")

    if not payload.approved:
        document.status = "rejected"
        document.reviewed_at = datetime.utcnow()
        document.review_notes = payload.notes
        db.add(OcrReviewEvent(document_id=document.id, id_personal=document.id_personal, action="rejected_document", notes=payload.notes))
        db.flush()
        return document

    rows_by_id = {row.id: row for row in document.rows}
    review_rows = list(payload.rows)
    if not review_rows:
        review_rows = [
            ReviewRowIn(row_id=row.id, approved=True)
            for row in document.rows
            if row.requires_review
        ]

    for item in review_rows:
        row = rows_by_id.get(item.row_id)
        if not row:
            raise HTTPException(status_code=400, detail=f"Fila no pertenece al documento: {item.row_id}")
        if not item.approved:
            row.validation_status = "rejected"
            row.requires_review = True
            row.validation_notes = item.notes or row.validation_notes
            continue

        material = _resolve_or_create_material(db, document, row, item.material_id, item.material_canonical)
        approved_price = item.price_value if item.price_value is not None else row.price_value
        if approved_price is None:
            raise HTTPException(status_code=400, detail=f"Fila {row.id} no tiene precio aprobado.")

        previous = {
            "material_id": row.approved_material_id,
            "price_value": row.approved_price_value,
            "status": row.validation_status,
        }
        row.approved_material_id = material.id
        row.approved_price_value = int(approved_price)
        row.requires_review = False
        row.validation_status = "corrected" if item.price_value is not None or item.material_canonical else "approved"
        row.review_reason = "none"
        row.reviewed_at = datetime.utcnow()
        row.validation_notes = item.notes

        _ensure_alias(db, document.id_personal, material, row.material_raw or material.canonical_name, row.section)
        _ensure_alias(db, document.id_personal, material, material.canonical_name, row.section)

        db.add(
            OcrReviewEvent(
                document_id=document.id,
                document_row_id=row.id,
                id_personal=document.id_personal,
                action="corrected_row" if row.validation_status == "corrected" else "approved_row",
                previous_value=previous,
                new_value={"material_id": material.id, "price_value": approved_price, "status": row.validation_status},
                notes=item.notes,
            )
        )

    unresolved = [row for row in document.rows if row.requires_review and row.validation_status != "rejected"]
    if unresolved:
        raise HTTPException(status_code=422, detail=f"Quedan {len(unresolved)} filas pendientes de revisión.")

    rejected = [row for row in document.rows if row.validation_status == "rejected"]
    if rejected:
        raise HTTPException(status_code=422, detail="Hay filas rechazadas. Rechaza el documento o corrige esas filas.")

    document.status = "processed"
    document.reviewed_at = datetime.utcnow()
    document.processed_at = datetime.utcnow()
    document.review_notes = payload.notes
    document.reviewed_json = _build_reviewed_json(document)
    document.rows_requiring_review = 0

    for row in document.rows:
        exists = db.query(PriceHistory).filter_by(document_row_id=row.id).one_or_none()
        if exists:
            continue
        price_value = row.approved_price_value if row.approved_price_value is not None else row.price_value
        material_id = row.approved_material_id or row.suggested_material_id
        if price_value is None or material_id is None:
            raise HTTPException(status_code=400, detail=f"Fila {row.id} no tiene material/precio final.")
        db.add(
            PriceHistory(
                document_id=document.id,
                document_row_id=row.id,
                id_personal=document.id_personal,
                material_id=material_id,
                observed_date=document.detected_date,
                section=row.section,
                price_value=price_value,
                price_text=str(price_value),
                source="reviewed",
            )
        )

    db.add(OcrReviewEvent(document_id=document.id, id_personal=document.id_personal, action="approved_document", notes=payload.notes))
    db.flush()
    return document


def _resolve_or_create_material(
    db: Session,
    document: OcrDocument,
    row: OcrDocumentRow,
    material_id: int | None,
    material_canonical: str | None,
) -> Material:
    if material_id:
        material = db.query(Material).filter_by(id=material_id, id_personal=document.id_personal).one_or_none()
        if not material:
            raise HTTPException(status_code=400, detail=f"Material no encontrado: {material_id}")
        return material

    canonical = material_canonical or row.material_ocr or row.material_raw
    if not canonical:
        raise HTTPException(status_code=400, detail=f"Fila {row.id} no tiene nombre de material.")
    normalized = normalize_for_exact_match(canonical)

    material = db.query(Material).filter_by(id_personal=document.id_personal, section=row.section, normalized_name=normalized).one_or_none()
    if material:
        return material

    material = Material(
        id_personal=document.id_personal,
        canonical_name=canonical.strip(),
        normalized_name=normalized,
        section=row.section,
        source="reviewed",
        first_seen_document_id=document.id,
        first_seen_row_id=row.id,
        approved_at=datetime.utcnow(),
    )
    db.add(material)
    db.flush()
    db.add(
        OcrReviewEvent(
            document_id=document.id,
            document_row_id=row.id,
            id_personal=document.id_personal,
            action="created_material",
            new_value={"material_id": material.id, "canonical_name": material.canonical_name},
        )
    )
    return material


def _ensure_alias(db: Session, id_personal: int, material: Material, alias_text: str, section: str) -> None:
    normalized = normalize_for_exact_match(alias_text)
    pending_duplicate = any(
        isinstance(item, MaterialAlias)
        and item.id_personal == id_personal
        and item.section == section
        and item.normalized_alias == normalized
        for item in db.new
    )
    if pending_duplicate:
        return

    exists = db.query(MaterialAlias).filter_by(id_personal=id_personal, section=section, normalized_alias=normalized).one_or_none()
    if exists:
        return
    db.add(
        MaterialAlias(
            id_personal=id_personal,
            material_id=material.id,
            section=section,
            alias_text=alias_text,
            normalized_alias=normalized,
            source="reviewed",
            match_rule="manual_link",
        )
    )


def _build_reviewed_json(document: OcrDocument) -> dict:
    return {
        "document_id": document.id,
        "status": "processed",
        "rows": [
            {
                "row_id": row.id,
                "section": row.section,
                "row_number": row.row_number,
                "material_id": row.approved_material_id or row.suggested_material_id,
                "material": row.material_ocr or row.material_raw,
                "price_value": row.approved_price_value if row.approved_price_value is not None else row.price_value,
                "validation_status": row.validation_status,
            }
            for row in document.rows
        ],
    }
