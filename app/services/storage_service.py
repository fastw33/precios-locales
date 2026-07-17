from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.core.config import get_settings


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_compressed_webp(image: np.ndarray, original_filename: str | None = None) -> dict:
    settings = get_settings()
    today = datetime.utcnow()
    relative_dir = Path(str(today.year)) / f"{today.month:02d}" / f"{today.day:02d}"
    target_dir = settings.upload_root / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{uuid.uuid4().hex}.webp"
    absolute_path = target_dir / file_name
    ok, buffer = cv2.imencode(
        ".webp",
        image,
        [int(cv2.IMWRITE_WEBP_QUALITY), settings.image_webp_quality],
    )
    if not ok:
        raise ValueError("No se pudo comprimir la imagen a WebP.")

    absolute_path.write_bytes(buffer.tobytes())
    relative_path = (Path(settings.upload_dir.name) / relative_dir / file_name).as_posix()

    public_url = None
    if settings.public_upload_base_url:
        public_url = f"{settings.public_upload_base_url}/{relative_path}"

    return {
        "path": relative_path,
        "absolute_path": str(absolute_path),
        "mime": "image/webp",
        "size": absolute_path.stat().st_size,
        "public_url": public_url,
        "original_filename": original_filename,
    }

