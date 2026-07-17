from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ValidationSettings(Base):
    __tablename__ = "validation_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_personal: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    max_auto_price_change_percent: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=10)
    min_material_confidence: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=70)
    min_price_confidence: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=70)
    allow_symbol_space_autocorrect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_review_for_new_material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_personal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(180), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(180), nullable=False)
    section: Mapped[str] = mapped_column(Enum("EXPORTACION", "NACIONAL", "OTRO"), nullable=False, default="OTRO")
    source: Mapped[str] = mapped_column(Enum("reviewed", "manual"), nullable=False, default="reviewed")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ocr_documents.id"), nullable=True)
    first_seen_row_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ocr_document_rows.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())

    aliases: Mapped[list["MaterialAlias"]] = relationship(back_populates="material")

    __table_args__ = (
        UniqueConstraint("id_personal", "section", "normalized_name", name="uq_material_personal_section_name"),
        Index("idx_material_personal", "id_personal"),
        Index("idx_material_section", "section"),
        Index("idx_material_active", "active"),
    )


class MaterialAlias(Base):
    __tablename__ = "material_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_personal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("materials.id"), nullable=False)
    section: Mapped[str] = mapped_column(Enum("EXPORTACION", "NACIONAL", "OTRO"), nullable=False, default="OTRO")
    alias_text: Mapped[str] = mapped_column(String(180), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(180), nullable=False)
    source: Mapped[str] = mapped_column(Enum("reviewed", "manual", "system"), nullable=False, default="reviewed")
    match_rule: Mapped[str] = mapped_column(Enum("exact", "symbol_space_variant", "manual_link"), nullable=False, default="manual_link")
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    material: Mapped[Material] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("id_personal", "section", "normalized_alias", name="uq_alias_personal_section"),
        Index("idx_alias_material", "material_id"),
        Index("idx_alias_personal", "id_personal"),
    )


class OcrDocument(Base):
    __tablename__ = "ocr_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_personal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Enum("pending_review", "processed", "rejected", "failed"), nullable=False, default="pending_review")
    engine: Mapped[str] = mapped_column(String(50), nullable=False)
    template: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    compressed_image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    compressed_image_mime: Mapped[str | None] = mapped_column(String(50), nullable=True)
    compressed_image_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_image_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_ocr_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    reviewed_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    template_compatible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_requiring_review: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prices_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    rows: Mapped[list["OcrDocumentRow"]] = relationship(back_populates="document")
    prices: Mapped[list["PriceHistory"]] = relationship(back_populates="document")

    __table_args__ = (
        Index("idx_documents_personal_status", "id_personal", "status"),
        Index("idx_documents_personal_date", "id_personal", "detected_date"),
        Index("idx_documents_personal_date_status", "id_personal", "detected_date", "status"),
        Index("idx_documents_uploaded_at", "uploaded_at"),
        Index("idx_documents_image_sha256", "image_sha256"),
    )


class OcrDocumentRow(Base):
    __tablename__ = "ocr_document_rows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ocr_documents.id"), nullable=False)
    id_personal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    section: Mapped[str] = mapped_column(Enum("EXPORTACION", "NACIONAL", "OTRO"), nullable=False, default="OTRO")
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    material_raw: Mapped[str | None] = mapped_column(String(180), nullable=True)
    material_ocr: Mapped[str | None] = mapped_column(String(180), nullable=True)
    material_normalized: Mapped[str | None] = mapped_column(String(180), nullable=True)
    suggested_material_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("materials.id"), nullable=True)
    approved_material_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("materials.id"), nullable=True)
    price_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    price_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_price_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    material_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    price_confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    match_type: Mapped[str | None] = mapped_column(Enum("exact_alias", "exact_material", "symbol_space_variant", "possible_text_change", "new_material", "no_match"), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_reason: Mapped[str] = mapped_column(Enum("none", "new_material", "possible_material_match", "text_changed", "price_out_of_range", "low_material_confidence", "low_price_confidence", "invalid_price", "ocr_requires_review"), nullable=False, default="none")
    validation_status: Mapped[str] = mapped_column(Enum("valid", "auto_corrected", "pending_review", "approved", "corrected", "rejected"), nullable=False, default="valid")
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    document: Mapped[OcrDocument] = relationship(back_populates="rows")

    __table_args__ = (
        UniqueConstraint("document_id", "section", "row_number", name="uq_document_section_row"),
        Index("idx_rows_personal_document", "id_personal", "document_id"),
        Index("idx_rows_material_normalized", "material_normalized"),
        Index("idx_rows_requires_review", "requires_review"),
        Index("idx_rows_validation_status", "validation_status"),
        Index("idx_rows_review_reason", "review_reason"),
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ocr_documents.id"), nullable=False)
    document_row_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ocr_document_rows.id"), nullable=False, unique=True)
    id_personal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    material_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("materials.id"), nullable=False)
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    section: Mapped[str] = mapped_column(Enum("EXPORTACION", "NACIONAL", "OTRO"), nullable=False, default="OTRO")
    price_value: Mapped[int] = mapped_column(Integer, nullable=False)
    price_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(Enum("ocr", "reviewed"), nullable=False, default="ocr")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    document: Mapped[OcrDocument] = relationship(back_populates="prices")

    __table_args__ = (
        Index("idx_price_personal_material_date", "id_personal", "material_id", "observed_date"),
        Index("idx_price_personal_date", "id_personal", "observed_date"),
        Index("idx_price_material_date", "material_id", "observed_date"),
    )


class OcrReviewEvent(Base):
    __tablename__ = "ocr_review_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ocr_documents.id"), nullable=False)
    document_row_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ocr_document_rows.id"), nullable=True)
    id_personal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(Enum("approved_document", "rejected_document", "approved_row", "corrected_row", "created_material", "linked_material", "created_alias", "corrected_material", "corrected_price"), nullable=False)
    previous_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_review_document", "document_id"),
        Index("idx_review_row", "document_row_id"),
        Index("idx_review_personal_created", "id_personal", "created_at"),
    )
