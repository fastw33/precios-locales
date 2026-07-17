from __future__ import annotations

from fastapi import UploadFile

from ocr_core import configure_tesseract, extract_template, image_bytes_to_bgr


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def run_ocr_from_bytes(data: bytes) -> tuple[dict, object]:
    configure_tesseract()
    image = image_bytes_to_bgr(data)
    result = extract_template(image)
    return result, image


def validate_upload_file(file: UploadFile, data: bytes, max_bytes: int) -> None:
    if not data:
        raise ValueError("La imagen está vacía.")
    if len(data) > max_bytes:
        raise ValueError("La imagen excede el tamaño máximo permitido.")
    if file.content_type and file.content_type.lower() not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Tipo de imagen no permitido: {file.content_type}")

