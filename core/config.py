"""
core/config.py  —  Phase 3 (Security hardening)
All secrets loaded from environment variables only.
Never hardcode secrets — .env file is gitignored.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional
import secrets


class Settings(BaseSettings):
    # ── MongoDB ─────────────────────────────────────────────────
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db:  str = "proeld"

    # ── JWT ─────────────────────────────────────────────────────
    # REQUIRED in production — will raise on startup if missing
    jwt_secret:                   str = ""
    jwt_algorithm:                str = "HS256"
    access_token_expire_minutes:  int = 480   # 8 hours
    refresh_token_expire_days:    int = 7

    # ── CORS ────────────────────────────────────────────────────
    # Comma-separated allowed origins for production
    # e.g. "https://proeld.app,https://www.proeld.app"
    allowed_origins: str = ""

    # ── Geocoding ───────────────────────────────────────────────
    nominatim_user_agent: str = "ProELD/3.1 (FMCSA ELD tablet; opensource)"

    # ── Rate limits ─────────────────────────────────────────────
    rate_limit_login:    str = "10/minute"
    rate_limit_register: str = "5/minute"
    rate_limit_api:      str = "120/minute"
    rate_limit_dot_pin:  str = "5/minute"

    # ── App ─────────────────────────────────────────────────────
    app_env:     str = "development"
    app_version: str = "3.2.0"   # Phase 3
    log_level:   str = "INFO"
    log_json:    bool = False

    # ── Security ────────────────────────────────────────────────
    # Minimum password entropy score (0-4, zxcvbn scale)
    min_password_score: int = 2

    model_config = {
        "env_file":          ".env",
        "env_file_encoding": "utf-8",
        "extra":             "ignore",
    }

    def validate_production_secrets(self) -> None:
        """Call at startup — raises if required secrets are missing in prod."""
        if self.app_env != "production":
            return
        errors = []
        if not self.jwt_secret or self.jwt_secret == "change-me-in-production":
            errors.append("JWT_SECRET must be set to a strong random value in production.")
        if len(self.jwt_secret) < 32:
            errors.append("JWT_SECRET must be at least 32 characters.")
        if "localhost" in self.mongo_uri or "127.0.0.1" in self.mongo_uri:
            errors.append("MONGO_URI must point to a remote database in production.")
        if not self.allowed_origins:
            errors.append("ALLOWED_ORIGINS must be set in production.")
        if errors:
            raise RuntimeError(
                "Production secrets validation failed:\n" +
                "\n".join(f"  - {e}" for e in errors)
            )

    @property
    def cors_origins(self) -> list[str]:
        """Parse ALLOWED_ORIGINS into a list."""
        if self.app_env == "development":
            return ["*"]
        if self.allowed_origins:
            return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        return []

    @staticmethod
    def generate_secret() -> str:
        """Helper: generate a strong JWT secret."""
        return secrets.token_hex(32)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()