from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api import materials, ocr, prices
from app.core.auth import auth_http_middleware
from app.core.config import get_settings
from app.core.database import engine


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

app.middleware("http")(auth_http_middleware)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"ok": True, "service": settings.app_name}


@app.get("/health/db", tags=["health"])
def health_db() -> dict:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return {
            "ok": False,
            "service": settings.app_name,
            "database": "unavailable",
            "detail": str(exc.__cause__ or exc),
        }
    return {"ok": True, "service": settings.app_name, "database": "available"}


app.include_router(ocr.router, prefix="/api")
app.include_router(prices.router, prefix="/api")
app.include_router(materials.router, prefix="/api")
