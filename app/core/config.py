from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "si"}


class Settings:
    app_name: str = os.getenv("APP_NAME", "Precios Locales OCR API")
    app_env: str = os.getenv("APP_ENV", "development")
    app_debug: bool = _bool_env("APP_DEBUG")
    cors_origins: list[str] = _csv_env("CORS_ORIGINS")
    cors_allow_methods: list[str] = _csv_env("CORS_ALLOW_METHODS")
    cors_allow_headers: list[str] = _csv_env("CORS_ALLOW_HEADERS")
    cors_allow_credentials: bool = _bool_env("CORS_ALLOW_CREDENTIALS")
    auth_public_paths: list[str] = _csv_env("AUTH_PUBLIC_PATHS") or ["/health", "/health/db"]

    database_url: str = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://usuario:password@localhost:3306/precios_locales?charset=utf8mb4",
    )

    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "uploads"))
    public_upload_base_url: str = os.getenv("PUBLIC_UPLOAD_BASE_URL", "").rstrip("/")
    image_webp_quality: int = int(os.getenv("IMAGE_WEBP_QUALITY", "85"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    internal_service_key: str = os.getenv("INTERNAL_SERVICE_KEY", "")

    @property
    def upload_root(self) -> Path:
        path = self.upload_dir
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
