from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import PROJECT_ROOT, get_settings
from app.core.database import get_db
from app.models import OcrDocument, OcrDocumentRow, OcrReviewEvent, PriceHistory
from app.schemas.ocr import DocumentProcessResponse, ReviewDocumentIn
from app.services.document_service import persist_ocr_result
from app.services.ocr_service import run_ocr_from_bytes, validate_upload_file
from app.services.review_service import review_document
from app.services.storage_service import save_compressed_webp, sha256_bytes


router = APIRouter(prefix="/ocr", tags=["ocr"])


@router.post("/process", response_model=DocumentProcessResponse)
async def process_ocr(
    id_personal: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DocumentProcessResponse:
    settings = get_settings()
    data = await file.read()
    try:
        validate_upload_file(file, data, settings.max_upload_bytes)
        ocr_result, image = await run_in_threadpool(run_ocr_from_bytes, data)
        compressed = await run_in_threadpool(save_compressed_webp, image, file.filename)
        document, rows = persist_ocr_result(
            db,
            id_personal=id_personal,
            ocr_result=ocr_result,
            original_filename=file.filename,
            original_image_size=len(data),
            compressed_image=compressed,
            image_sha256=sha256_bytes(data),
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "No se pudo conectar o escribir en la base de datos. Revisa DATABASE_URL en .env y que la base precios_locales exista.",
                "database_error": str(exc.__cause__ or exc),
            },
        ) from exc
    except Exception:
        db.rollback()
        raise

    review_items = [
        {
            "row_id": row.id,
            "section": row.section,
            "row_number": row.row_number,
            "material_raw": row.material_raw,
            "material_ocr": row.material_ocr,
            "material_normalized": row.material_normalized,
            "suggested_material_id": row.suggested_material_id,
            "price_text": row.price_text,
            "price_value": row.price_value,
            "review_reason": row.review_reason,
            "validation_notes": row.validation_notes,
        }
        for row in rows
        if row.requires_review
    ]

    return DocumentProcessResponse(
        ok=document.status == "processed",
        status=document.status,
        document_id=document.id,
        message="OCR procesado correctamente." if document.status == "processed" else "Hay valores que requieren revisión humana.",
        rows_requiring_review=document.rows_requiring_review,
        review_items=review_items,
        ocr_result=ocr_result,
    )


@router.get("/documents")
def list_ocr_documents(id_personal: int, db: Session = Depends(get_db)) -> list[dict]:
    documents = (
        db.query(OcrDocument)
        .filter(OcrDocument.id_personal == id_personal)
        .order_by(OcrDocument.detected_date.desc(), OcrDocument.id.desc())
        .all()
    )
    return [
        {
            "id": document.id,
            "id_personal": document.id_personal,
            "status": document.status,
            "detected_date": document.detected_date,
            "uploaded_at": document.uploaded_at,
            "processed_at": document.processed_at,
            "reviewed_at": document.reviewed_at,
            "original_filename": document.original_filename,
            "compressed_image_path": document.compressed_image_path,
            "compressed_image_mime": document.compressed_image_mime,
            "compressed_image_size": document.compressed_image_size,
            "total_rows": document.total_rows,
            "rows_requiring_review": document.rows_requiring_review,
            "prices_detected": document.prices_detected,
            "image_url": f"/api/ocr/{document.id}/image",
        }
        for document in documents
    ]


@router.get("/{document_id}/image")
def download_ocr_image(
    document_id: int,
    download: bool = Query(False),
    db: Session = Depends(get_db),
) -> FileResponse:
    document = db.query(OcrDocument).filter_by(id=document_id).one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")

    image_path = (PROJECT_ROOT / document.compressed_image_path).resolve()
    upload_root = get_settings().upload_root.resolve()
    if not image_path.is_file() or upload_root not in image_path.parents:
        raise HTTPException(status_code=404, detail="Imagen comprimida no encontrada.")

    filename = f"lista-precios-{document.detected_date or document.id}.webp"
    return FileResponse(
        path=Path(image_path),
        media_type=document.compressed_image_mime or "image/webp",
        filename=filename if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete("/{document_id}")
def delete_ocr_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    document = db.query(OcrDocument).filter_by(id=document_id).one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")

    if document.status == "processed":
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar una carga ya procesada porque tiene histórico de precios.",
        )

    has_prices = db.query(PriceHistory.id).filter_by(document_id=document_id).first()
    if has_prices:
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar este documento porque ya tiene precios guardados.",
        )

    image_path = (PROJECT_ROOT / document.compressed_image_path).resolve()
    upload_root = get_settings().upload_root.resolve()

    db.query(OcrReviewEvent).filter(OcrReviewEvent.document_id == document_id).delete(
        synchronize_session=False
    )
    db.query(OcrDocumentRow).filter(OcrDocumentRow.document_id == document_id).delete(
        synchronize_session=False
    )
    db.delete(document)
    db.commit()

    if image_path.is_file() and upload_root in image_path.parents:
        image_path.unlink(missing_ok=True)

    return {"ok": True, "document_id": document_id, "message": "Carga eliminada."}


@router.get("/{document_id}")
def get_ocr_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    document = db.query(OcrDocument).filter_by(id=document_id).one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    return {
        "id": document.id,
        "id_personal": document.id_personal,
        "status": document.status,
        "detected_date": document.detected_date,
        "uploaded_at": document.uploaded_at,
        "compressed_image_path": document.compressed_image_path,
        "total_rows": document.total_rows,
        "rows_requiring_review": document.rows_requiring_review,
        "prices_detected": document.prices_detected,
        "rows": [
            {
                "row_id": row.id,
                "section": row.section,
                "row_number": row.row_number,
                "material_raw": row.material_raw,
                "material_ocr": row.material_ocr,
                "material_normalized": row.material_normalized,
                "suggested_material_id": row.suggested_material_id,
                "approved_material_id": row.approved_material_id,
                "price_text": row.price_text,
                "price_value": row.price_value,
                "approved_price_value": row.approved_price_value,
                "requires_review": row.requires_review,
                "review_reason": row.review_reason,
                "validation_status": row.validation_status,
                "validation_notes": row.validation_notes,
            }
            for row in sorted(document.rows, key=lambda item: (item.section, item.row_number))
        ],
    }


@router.post("/{document_id}/review")
def review_ocr_document(
    document_id: int,
    payload: ReviewDocumentIn,
    db: Session = Depends(get_db),
) -> dict:
    try:
        document = review_document(db, document_id, payload)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "No se pudo conectar o escribir en la base de datos. Revisa DATABASE_URL en .env.",
                "database_error": str(exc.__cause__ or exc),
            },
        ) from exc
    except Exception:
        db.rollback()
        raise
    return {
        "ok": document.status == "processed",
        "status": document.status,
        "document_id": document.id,
        "message": "Documento aprobado y precios guardados en histórico." if document.status == "processed" else "Documento actualizado.",
    }
