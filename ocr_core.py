from __future__ import annotations

import io
import os
import re
import shutil
from dataclasses import dataclass
from statistics import median
from typing import Any

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

TARGET_WIDTH = 849
TARGET_HEIGHT = 1319
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_TESSDATA = os.path.join(PROJECT_DIR, "tessdata")


class OCRSetupError(RuntimeError):
    pass


def configure_tesseract() -> str:
    """Detecta Tesseract en Linux y en rutas comunes de Windows."""
    candidates = [
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            required = [
                os.path.join(LOCAL_TESSDATA, "spa.traineddata"),
                os.path.join(LOCAL_TESSDATA, "eng.traineddata"),
            ]
            missing = [path for path in required if not os.path.exists(path)]
            if missing:
                raise OCRSetupError(
                    "Faltan los archivos de idioma spa/eng en la carpeta tessdata. "
                    "Ejecuta instalar_consola.bat."
                )
            os.environ["TESSDATA_PREFIX"] = LOCAL_TESSDATA
            return candidate
    raise OCRSetupError(
        "No se encontro Tesseract OCR. Ejecuta instalar_consola.bat."
    )


def image_bytes_to_bgr(data: bytes) -> np.ndarray:
    pil = Image.open(io.BytesIO(data)).convert("RGB")
    rgb = np.array(pil)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def load_image(path: str) -> np.ndarray:
    image = cv2.imread(path)
    if image is None:
        raise ValueError(f"No se pudo abrir la imagen: {path}")
    return image


def normalize_to_template(image: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Normaliza orientacion y tamano para que las coordenadas sean repetibles."""
    h, w = image.shape[:2]
    rotated = False
    if w > h:
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        h, w = image.shape[:2]
        rotated = True

    ratio = w / h
    ratio_difference = abs(ratio - TARGET_RATIO) / TARGET_RATIO
    resized = cv2.resize(
        image,
        (TARGET_WIDTH, TARGET_HEIGHT),
        interpolation=cv2.INTER_CUBIC if w < TARGET_WIDTH else cv2.INTER_AREA,
    )
    return resized, {
        "original_width": int(w),
        "original_height": int(h),
        "rotated": rotated,
        "original_ratio": round(ratio, 5),
        "template_ratio": round(TARGET_RATIO, 5),
        "ratio_difference_percent": round(ratio_difference * 100, 2),
        "template_compatible": ratio_difference <= 0.08,
    }


def _prepare_crop(
    crop: np.ndarray,
    *,
    scale: int,
    sharpen_strength: float = 1.7,
    blur_sigma: float = 0.9,
    border: int = 30,
) -> np.ndarray:
    if crop is None or crop.size == 0:
        raise ValueError("El recorte OCR está vacío.")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    upscaled = cv2.resize(
        gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
    )
    blur = cv2.GaussianBlur(upscaled, (0, 0), blur_sigma)
    sharpened = cv2.addWeighted(
        upscaled,
        sharpen_strength,
        blur,
        -(sharpen_strength - 1.0),
        0,
    )
    _, binary = cv2.threshold(
        sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    return cv2.copyMakeBorder(
        binary, border, border, border, border, cv2.BORDER_CONSTANT, value=255
    )


def _empty_ocr_result() -> dict[str, Any]:
    return {"text": "", "confidence": None}


def _clean_ocr_text(value: str) -> str:
    value = value.replace("\x0c", " ")
    value = value.replace("|", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _mean_confidence(data: dict[str, list[Any]]) -> float | None:
    values: list[float] = []
    for raw_conf, raw_text in zip(data.get("conf", []), data.get("text", [])):
        if not str(raw_text).strip():
            continue
        try:
            conf = float(raw_conf)
        except (TypeError, ValueError):
            continue
        if conf >= 0:
            values.append(conf)
    return round(sum(values) / len(values), 2) if values else None


def _text_from_data(data: dict[str, list[Any]], multiline: bool = False) -> str:
    if not multiline:
        words = [str(value).strip() for value in data.get("text", []) if str(value).strip()]
        return _clean_ocr_text(" ".join(words))

    grouped: dict[tuple[int, int, int, int], list[tuple[int, str]]] = {}
    tops: dict[tuple[int, int, int, int], int] = {}
    for index, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text).strip()
        if not text:
            continue
        key = (
            int(data["page_num"][index]),
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        grouped.setdefault(key, []).append((int(data["left"][index]), text))
        tops[key] = min(tops.get(key, int(data["top"][index])), int(data["top"][index]))

    lines: list[tuple[int, str]] = []
    for key, words in grouped.items():
        words.sort(key=lambda item: item[0])
        line = _clean_ocr_text(" ".join(word for _, word in words))
        if line:
            lines.append((tops[key], line))
    lines.sort(key=lambda item: item[0])
    return "\n".join(line for _, line in lines)


def ocr_single_line(crop: np.ndarray, *, numeric: bool = False) -> dict[str, Any]:
    if crop is None or crop.size == 0:
        return _empty_ocr_result()
    processed = _prepare_crop(
        crop,
        scale=6 if numeric else 4,
        sharpen_strength=1.8 if numeric else 1.65,
        blur_sigma=1.0 if numeric else 0.8,
        border=40 if numeric else 25,
    )
    lang = "eng" if numeric else "spa"
    config = "--oem 3 --psm 7"
    if numeric:
        config += " -c tessedit_char_whitelist=0123456789."

    data = pytesseract.image_to_data(
        processed, lang=lang, config=config, output_type=Output.DICT
    )
    return {
        "text": _text_from_data(data),
        "confidence": _mean_confidence(data),
    }


def ocr_block(crop: np.ndarray, *, psm: int = 6, scale: int = 3) -> dict[str, Any]:
    if crop is None or crop.size == 0:
        return _empty_ocr_result()
    processed = _prepare_crop(
        crop, scale=scale, sharpen_strength=1.6, blur_sigma=0.8, border=20
    )
    config = f"--oem 3 --psm {psm}"
    data = pytesseract.image_to_data(
        processed, lang="spa", config=config, output_type=Output.DICT
    )
    return {"text": _text_from_data(data, multiline=True), "confidence": _mean_confidence(data)}


def ocr_name_column(crop: np.ndarray, row_count: int, row_height: int = 38) -> list[dict[str, Any]]:
    if crop is None or crop.size == 0:
        return [_empty_ocr_result() for _ in range(row_count)]
    scale = 3
    border = 20
    processed = _prepare_crop(
        crop, scale=scale, sharpen_strength=1.65, blur_sigma=0.8, border=border
    )
    data = pytesseract.image_to_data(
        processed, lang="spa", config="--oem 3 --psm 11", output_type=Output.DICT
    )
    rows: list[list[tuple[int, str, float]]] = [[] for _ in range(row_count)]
    for index, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text).strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][index])
        except (TypeError, ValueError):
            conf = -1.0
        center_y = int(data["top"][index]) + int(data["height"][index]) / 2
        original_y = (center_y - border) / scale
        row_index = int(original_y // row_height)
        if 0 <= row_index < row_count:
            rows[row_index].append((int(data["left"][index]), text, conf))

    results: list[dict[str, Any]] = []
    for words in rows:
        words.sort(key=lambda item: item[0])
        text = _clean_ocr_text(" ".join(item[1] for item in words))
        confs = [item[2] for item in words if item[2] >= 0]
        confidence = round(sum(confs) / len(confs), 2) if confs else None
        results.append({"text": text, "confidence": confidence})
    return results


def normalize_material_name(text: str) -> str:
    """Solo corrige espacios y dos errores OCR repetitivos del simbolo #."""
    value = _clean_ocr_text(text).upper()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^CH[.,]?\s+", "CH. ", value)
    value = re.sub(r"\bRAD,\s*", "RAD. ", value)
    if value.startswith("CH. COBRE") and "BRILLANTE" not in value:
        suffix = value.replace("CH. COBRE", "", 1)
        if "2" in suffix:
            value = "CH. COBRE #2"
        elif "1" in suffix:
            value = "CH. COBRE #1"
    return value.strip()


def parse_price(text: str) -> int | None:
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned:
        return None
    if cleaned.count(".") == 1:
        left, right = cleaned.split(".", 1)
        if left.isdigit() and right.isdigit() and 0 < len(right) < 3:
            return int(left + right.ljust(3, "0"))
    digits = cleaned.replace(".", "")
    return int(digits) if digits.isdigit() else None


def _price_uses_short_thousands(text: str) -> bool:
    cleaned = re.sub(r"[^0-9.]", "", text)
    if cleaned.count(".") != 1:
        return False
    left, right = cleaned.split(".", 1)
    return left.isdigit() and right.isdigit() and 0 < len(right) < 3


def _cell(image: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
    height, width = image.shape[:2]
    safe_x1 = max(0, min(width, x1))
    safe_x2 = max(0, min(width, x2))
    safe_y1 = max(0, min(height, y1))
    safe_y2 = max(0, min(height, y2))
    if safe_x1 >= safe_x2 or safe_y1 >= safe_y2:
        return image[0:0, 0:0]
    return image[safe_y1:safe_y2, safe_x1:safe_x2]


def _horizontal_line_ys(
    image: np.ndarray,
    *,
    x1: int = 0,
    x2: int = 360,
    y_limit: int = 360,
    min_score: float = 0.75,
) -> list[int]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    y_limit = min(y_limit, gray.shape[0])
    x2 = min(x2, gray.shape[1])
    dark = gray[:y_limit, x1:x2] < 85
    scores = dark.mean(axis=1)
    indexes = [index for index, score in enumerate(scores) if score >= min_score]
    if not indexes:
        return []

    groups: list[tuple[int, int]] = []
    start = previous = indexes[0]
    for index in indexes[1:]:
        if index <= previous + 1:
            previous = index
        else:
            groups.append((start, previous))
            start = previous = index
    groups.append((start, previous))
    return [int(round((start + end) / 2)) for start, end in groups]


def _top_is_table_header(image: np.ndarray) -> bool:
    top = image[: min(55, image.shape[0]), : min(350, image.shape[1])]
    if top.size == 0:
        return False
    b, g, r = cv2.split(top)
    blue_mask = (b > 120) & (g > 100) & (r < 220) & (b > r + 8) & (g > r - 20)
    return float(blue_mask.mean()) >= 0.45


def _cropped_table_layout(image: np.ndarray) -> dict[str, int] | None:
    if not _top_is_table_header(image):
        return None

    line_ys = _horizontal_line_ys(image, y_limit=360)
    first_data_line = next((y for y in line_ys if 25 <= y <= 85), None)
    if first_data_line is None:
        return None

    diffs = [
        line_ys[index + 1] - line_ys[index]
        for index in range(len(line_ys) - 1)
        if 30 <= line_ys[index + 1] - line_ys[index] <= 55
    ]
    row_height = int(round(median(diffs))) if diffs else 42
    return {
        "row_start": first_data_line + 1,
        "row_height": row_height,
        "layout_source": "cropped_table_header",
    }


def _template_layout(image_info: dict[str, Any], image: np.ndarray | None = None) -> dict[str, Any]:
    """Ajusta filas cuando la foto viene con una relación cercana, pero no idéntica."""
    if image is not None:
        cropped_layout = _cropped_table_layout(image)
        if cropped_layout:
            return cropped_layout

    original_ratio = float(image_info.get("original_ratio") or TARGET_RATIO)
    vertical_layout_scale = min(max(original_ratio / TARGET_RATIO, 0.92), 1.12)
    row_start = int(round(168 * vertical_layout_scale))
    row_height = int(round(38 * vertical_layout_scale))
    return {
        "row_start": row_start,
        "row_height": row_height,
        "layout_source": "full_template_ratio",
    }


def _trim_trailing_empty_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trimmed = list(rows)
    while trimmed:
        last = trimmed[-1]
        material = _clean_ocr_text(last.get("material_raw") or last.get("material") or "")
        price_text = _clean_ocr_text(last.get("price_text") or "")
        if material or price_text or last.get("price_value") is not None:
            break
        trimmed.pop()
    return trimmed


def extract_template(image: np.ndarray) -> dict[str, Any]:
    normalized, image_info = normalize_to_template(image)

    metadata_regions = {
        "title": (220, 0, 605, 60),
        "code": (605, 0, 849, 21),
        "version": (605, 20, 849, 41),
        "validity": (605, 40, 849, 61),
        "slogan": (0, 60, 849, 92),
        "date_address": (0, 92, 849, 132),
    }
    metadata: dict[str, Any] = {}
    for key, coords in metadata_regions.items():
        result = ocr_single_line(_cell(normalized, *coords), numeric=False)
        metadata[key] = result

    export_rows: list[dict[str, Any]] = []
    national_rows: list[dict[str, Any]] = []

    layout = _template_layout(image_info, normalized)
    row_start = layout["row_start"]
    row_height = layout["row_height"]

    export_materials = ocr_name_column(
        _cell(normalized, 2, row_start, 218, row_start + 28 * row_height), 28, row_height
    )
    national_materials = ocr_name_column(
        _cell(normalized, 430, row_start, 603, row_start + 5 * row_height), 5, row_height
    )

    for index in range(28):
        y1 = row_start + index * row_height
        y2 = y1 + row_height
        material = export_materials[index]
        price = ocr_single_line(
            _cell(normalized, 222, y1 + 2, 349, y2 - 2), numeric=True
        )
        normalized_name = normalize_material_name(material["text"])
        price_value = parse_price(price["text"])
        price_autocorrected = price_value is not None and _price_uses_short_thousands(price["text"])
        low_price_confidence = (
            price["confidence"] is not None
            and price["confidence"] < 70
            and not price_autocorrected
        )
        export_rows.append(
            {
                "section": "EXPORTACION",
                "row": index + 1,
                "material_raw": material["text"],
                "material": normalized_name,
                "normalization_applied": normalized_name != material["text"].upper().strip(),
                "price_text": price["text"],
                "price_value": price_value,
                "price_autocorrected": price_autocorrected,
                "material_confidence": material["confidence"],
                "price_confidence": price["confidence"],
                "requires_review": (
                    not normalized_name
                    or price_value is None
                    or (material["confidence"] is not None and material["confidence"] < 70)
                    or low_price_confidence
                ),
            }
        )

    for index in range(5):
        y1 = row_start + index * row_height
        y2 = y1 + row_height
        material = national_materials[index]
        price = ocr_single_line(
            _cell(normalized, 607, y1 + 2, 847, y2 - 2), numeric=True
        )
        normalized_name = normalize_material_name(material["text"])
        price_value = parse_price(price["text"])
        price_autocorrected = price_value is not None and _price_uses_short_thousands(price["text"])
        low_price_confidence = (
            price["confidence"] is not None
            and price["confidence"] < 70
            and not price_autocorrected
        )
        national_rows.append(
            {
                "section": "NACIONAL",
                "row": index + 1,
                "material_raw": material["text"],
                "material": normalized_name,
                "normalization_applied": normalized_name != material["text"].upper().strip(),
                "price_text": price["text"],
                "price_value": price_value,
                "price_autocorrected": price_autocorrected,
                "material_confidence": material["confidence"],
                "price_confidence": price["confidence"],
                "requires_review": (
                    not normalized_name
                    or price_value is None
                    or (material["confidence"] is not None and material["confidence"] < 70)
                    or low_price_confidence
                ),
            }
        )

    export_rows = _trim_trailing_empty_rows(export_rows)
    national_rows = _trim_trailing_empty_rows(national_rows)

    notes_y1 = row_start + 5 * row_height
    notes = ocr_block(_cell(normalized, 428, notes_y1, 849, 1194), psm=6, scale=3)
    raw_full = ocr_block(normalized, psm=11, scale=2)

    text_lines = [
        metadata["title"]["text"],
        metadata["code"]["text"],
        metadata["version"]["text"],
        metadata["validity"]["text"],
        metadata["slogan"]["text"],
        metadata["date_address"]["text"],
        "",
        "EXPORTACION",
    ]
    text_lines.extend(
        f'{row["material"]} | {row["price_text"]}' for row in export_rows
    )
    text_lines.extend(["", "NACIONAL"])
    text_lines.extend(
        f'{row["material"]} | {row["price_text"]}' for row in national_rows
    )
    text_lines.extend(["", "NOTAS", notes["text"]])
    standardized_text = "\n".join(line for line in text_lines if line is not None).strip()

    all_rows = export_rows + national_rows
    return {
        "engine": "tesseract-local",
        "template": "CIMETALES_LISTA_PRECIOS_V1",
        "image_info": image_info,
        "template_layout": layout,
        "metadata": metadata,
        "exportacion": export_rows,
        "nacional": national_rows,
        "notes": notes,
        "standardized_text": standardized_text,
        "raw_full_ocr": raw_full,
        "summary": {
            "export_rows": len(export_rows),
            "national_rows": len(national_rows),
            "total_rows": len(all_rows),
            "rows_requiring_review": sum(1 for row in all_rows if row["requires_review"]),
            "prices_detected": sum(1 for row in all_rows if row["price_value"] is not None),
        },
    }
