from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import require_personal_access
from app.core.database import get_db
from app.models import Material


router = APIRouter(prefix="/materials", tags=["materials"])


@router.get("")
def list_materials(
    id_personal: int,
    request: Request,
    active: bool = True,
    db: Session = Depends(get_db),
) -> list[dict]:
    require_personal_access(id_personal, request)
    rows = (
        db.query(Material)
        .filter(Material.active == active)
        .order_by(Material.section, Material.canonical_name)
        .all()
    )
    return [
        {
            "id": row.id,
            "canonical_name": row.canonical_name,
            "normalized_name": row.normalized_name,
            "section": row.section,
            "active": row.active,
            "id_personal": row.id_personal,
            "uploaded_by_id_personal": row.id_personal,
        }
        for row in rows
    ]
