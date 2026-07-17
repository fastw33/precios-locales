from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewRowIn(BaseModel):
    row_id: int
    approved: bool = True
    material_id: int | None = None
    material_canonical: str | None = None
    price_value: int | None = None
    notes: str | None = None


class ReviewDocumentIn(BaseModel):
    approved: bool = True
    rows: list[ReviewRowIn] = Field(default_factory=list)
    notes: str | None = None


class DocumentProcessResponse(BaseModel):
    ok: bool
    status: str
    document_id: int
    message: str
    rows_requiring_review: int
    review_items: list[dict] = Field(default_factory=list)
    ocr_result: dict | None = None

