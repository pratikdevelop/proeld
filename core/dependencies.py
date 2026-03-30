"""
core/dependencies.py
FastAPI dependency injectors for auth.

Usage in routers:
    @router.get("/logs")
    async def get_logs(driver: DriverDoc = Depends(require_driver)):
        ...
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError

from .security import decode_token
from .database import get_db

_bearer = HTTPBearer(auto_error=True)


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Decode JWT and return the payload. Raises 401 on any failure."""
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Refresh tokens cannot access this endpoint.")
    return payload


async def require_driver(payload: dict = Depends(_get_current_user)) -> dict:
    """Requires role == driver."""
    if payload.get("role") not in ("driver", "fleet_manager"):
        raise HTTPException(status_code=403, detail="Driver access required.")
    return payload


async def require_fleet(payload: dict = Depends(_get_current_user)) -> dict:
    """Requires role == fleet_manager."""
    if payload.get("role") != "fleet_manager":
        raise HTTPException(status_code=403, detail="Fleet manager access required.")
    return payload


async def require_any_auth(payload: dict = Depends(_get_current_user)) -> dict:
    """Any authenticated role is accepted."""
    return payload