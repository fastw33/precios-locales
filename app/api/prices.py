from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Material, PriceHistory


router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("/latest")
def latest_prices(id_personal: int, db: Session = Depends(get_db)) -> list[dict]:
    latest_subquery = (
        db.query(
            PriceHistory.material_id.label("material_id"),
            func.max(PriceHistory.observed_date).label("last_date"),
        )
        .filter(PriceHistory.id_personal == id_personal)
        .group_by(PriceHistory.material_id)
        .subquery()
    )

    rows = (
        db.query(PriceHistory, Material)
        .join(Material, Material.id == PriceHistory.material_id)
        .join(
            latest_subquery,
            (latest_subquery.c.material_id == PriceHistory.material_id)
            & (latest_subquery.c.last_date == PriceHistory.observed_date),
        )
        .filter(PriceHistory.id_personal == id_personal)
        .order_by(Material.canonical_name)
        .all()
    )

    return [
        {
            "material_id": material.id,
            "material": material.canonical_name,
            "section": material.section,
            "price_value": price.price_value,
            "observed_date": price.observed_date,
        }
        for price, material in rows
    ]


@router.get("/history")
def material_history(
    id_personal: int,
    material_id: int,
    desde: date,
    hasta: date,
    db: Session = Depends(get_db),
) -> dict:
    _validate_range(desde, hasta)
    material = db.query(Material).filter_by(id=material_id, id_personal=id_personal).one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material no encontrado.")

    rows = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.id_personal == id_personal,
            PriceHistory.material_id == material_id,
            PriceHistory.observed_date.between(desde, hasta),
        )
        .order_by(PriceHistory.observed_date)
        .all()
    )
    return {
        "material_id": material.id,
        "material": material.canonical_name,
        "desde": desde,
        "hasta": hasta,
        "data": [{"date": row.observed_date, "price_value": row.price_value} for row in rows],
    }


@router.get("/compare-materials")
def compare_materials(
    id_personal: int,
    material_ids: str = Query(..., description="IDs separados por coma, ejemplo: 1,2,3"),
    desde: date = Query(...),
    hasta: date = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    _validate_range(desde, hasta)
    ids = _parse_ids(material_ids)
    rows = (
        db.query(PriceHistory, Material)
        .join(Material, Material.id == PriceHistory.material_id)
        .filter(
            PriceHistory.id_personal == id_personal,
            PriceHistory.material_id.in_(ids),
            PriceHistory.observed_date.between(desde, hasta),
        )
        .order_by(PriceHistory.observed_date, Material.canonical_name)
        .all()
    )

    series: dict[int, dict] = {}
    for price, material in rows:
        series.setdefault(
            material.id,
            {"material_id": material.id, "material": material.canonical_name, "section": material.section, "data": []},
        )["data"].append({"date": price.observed_date, "price_value": price.price_value})

    return {"desde": desde, "hasta": hasta, "series": list(series.values())}


@router.get("/compare-periods")
def compare_periods(
    id_personal: int,
    material_id: int,
    period_type: str = Query(..., pattern="^(year|month|day)$"),
    periods: str = Query(..., description="Periodos separados por coma. year: 2025,2026. month: 2026-06,2026-07. day: 2026-07-01,2026-07-17"),
    db: Session = Depends(get_db),
) -> dict:
    material = db.query(Material).filter_by(id=material_id, id_personal=id_personal).one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material no encontrado.")

    parsed_periods = [_parse_period(period_type, item.strip()) for item in periods.split(",") if item.strip()]
    if not parsed_periods:
        raise HTTPException(status_code=400, detail="Debe enviar al menos un periodo.")

    series = []
    for label, desde, hasta in parsed_periods:
        rows = (
            db.query(PriceHistory)
            .filter(
                PriceHistory.id_personal == id_personal,
                PriceHistory.material_id == material_id,
                PriceHistory.observed_date.between(desde, hasta),
            )
            .order_by(PriceHistory.observed_date)
            .all()
        )
        series.append(
            {
                "period": label,
                "desde": desde,
                "hasta": hasta,
                "data": [{"date": row.observed_date, "price_value": row.price_value} for row in rows],
            }
        )

    return {
        "material_id": material.id,
        "material": material.canonical_name,
        "period_type": period_type,
        "series": series,
    }


def _validate_range(desde: date, hasta: date) -> None:
    if desde > hasta:
        raise HTTPException(status_code=400, detail="La fecha 'desde' no puede ser mayor que 'hasta'.")


def _parse_ids(value: str) -> list[int]:
    try:
        ids = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="material_ids debe contener IDs numéricos separados por coma.") from exc
    if not ids:
        raise HTTPException(status_code=400, detail="Debe enviar al menos un material_id.")
    return ids


def _parse_period(period_type: str, value: str) -> tuple[str, date, date]:
    try:
        if period_type == "year":
            year = int(value)
            return value, date(year, 1, 1), date(year, 12, 31)
        if period_type == "month":
            parsed = datetime.strptime(value, "%Y-%m").date()
            last_day = monthrange(parsed.year, parsed.month)[1]
            return value, date(parsed.year, parsed.month, 1), date(parsed.year, parsed.month, last_day)
        if period_type == "day":
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
            return value, parsed, parsed
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Periodo inválido para {period_type}: {value}") from exc
    raise HTTPException(status_code=400, detail="period_type inválido.")
