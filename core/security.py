"""
core/security.py
Password hashing (bcrypt) and JWT encode/decode.
All auth logic lives here — routers only call these helpers.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal
import secrets

from passlib.context import CryptContext
from jose import jwt, JWTError

from .config import settings

# ── Password hashing ─────────────────────────────────────────
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ── JWT ──────────────────────────────────────────────────────
TokenType = Literal["access", "refresh"]


def create_token(
    subject: str,           # driver_id or user_id
    role: str,              # "driver" | "fleet_manager" | "dot_officer"
    token_type: TokenType = "access",
    extra: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc)

    if token_type == "access":
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expire = now + timedelta(days=settings.refresh_token_expire_days)

    payload = {
        "sub":  subject,
        "role": role,
        "type": token_type,
        "iat":  now,
        "exp":  expire,
        **(extra or {}),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """
    Returns decoded payload dict.
    Raises JWTError (fastapi can convert to 401) on any failure.
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )


def create_access_token(subject: str, role: str = "driver") -> str:
    """Convenience alias — creates an access JWT for a driver."""
    return create_token(subject=subject, role=role, token_type="access")


def generate_refresh_token() -> str:
    """Cryptographically secure opaque refresh token (stored in DB)."""
    return secrets.token_urlsafe(48)


# ── DOT PIN ──────────────────────────────────────────────────
def hash_dot_pin(pin: str) -> str:
    return _pwd_ctx.hash(pin)


def verify_dot_pin(plain_pin: str, stored_hash: str) -> bool:
    """
    Validates a DOT inspection PIN against the bcrypt hash in DB.
    Never compare pins client-side.
    """
    if not stored_hash:
        return False
    return _pwd_ctx.verify(plain_pin, stored_hash)