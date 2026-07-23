from __future__ import annotations

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWTError
from starlette.responses import JSONResponse

from app.core.config import get_settings


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


def _token_personal_id(payload: dict) -> str:
    personal = payload.get("personal") if isinstance(payload.get("personal"), dict) else {}
    value = (
        payload.get("id_personal")
        or payload.get("Id_personal")
        or personal.get("id_personal")
        or personal.get("Id_personal")
    )
    return str(value or "").strip()


def verify_request(request: Request) -> dict:
    settings = get_settings()

    internal_key = (settings.internal_service_key or "").strip()
    incoming_internal_key = request.headers.get("x-internal-service-key", "").strip()
    if internal_key and incoming_internal_key and incoming_internal_key == internal_key:
        return {"internal_service": True}

    jwt_secret = (settings.jwt_secret or "").strip()
    if not jwt_secret:
        raise HTTPException(
            status_code=503,
            detail="JWT_SECRET no configurado en la API segura.",
        )

    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise _unauthorized("Token no proporcionado")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _unauthorized("Token no proporcionado")

    try:
        return jwt.decode(token, jwt_secret, algorithms=["HS256"])
    except PyJWTError as exc:
        raise _unauthorized("Token invalido o expirado") from exc


async def auth_http_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    try:
        request.state.usuario = verify_request(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return await call_next(request)


def require_personal_access(id_personal: int | str, request: Request) -> None:
    usuario = getattr(request.state, "usuario", {}) or {}
    if usuario.get("internal_service"):
        return

    token_id_personal = _token_personal_id(usuario)
    requested_id_personal = str(id_personal or "").strip()
    if not token_id_personal or token_id_personal != requested_id_personal:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para consultar informacion de otro usuario.",
        )
