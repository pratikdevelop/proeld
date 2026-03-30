"""
core/security_headers.py  —  Phase 3 (Security hardening)
Adds HTTP security headers to every response:
  - Strict-Transport-Security  (HSTS — forces HTTPS)
  - Content-Security-Policy    (blocks XSS, restricts resource origins)
  - X-Content-Type-Options     (prevents MIME sniffing)
  - X-Frame-Options            (blocks clickjacking)
  - Referrer-Policy            (limits referrer leakage)
  - Permissions-Policy         (restricts browser APIs to what we need)
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # HSTS — only in production (HTTPS must be live first)
        if settings.app_env == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # CSP — tightly scoped to what ProELD actually loads
        # Adjust cdn sources if you add new libraries
        csp_parts = [
            "default-src 'self'",
            # Scripts: self + CDN sources used by index.html
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com "
            "https://unpkg.com https://cdnjs.cloudflare.com",
            # Styles: self + Google Fonts + CDN
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
            "https://unpkg.com https://cdnjs.cloudflare.com",
            # Fonts: Google Fonts CDN
            "font-src 'self' https://fonts.gstatic.com",
            # Images: self + OpenStreetMap tiles + data URIs (for canvas)
            "img-src 'self' data: blob: https://*.tile.openstreetmap.org "
            "https://nominatim.openstreetmap.org",
            # Connections: self + Atlas + Nominatim + WSS for telemetry
            "connect-src 'self' wss: https://nominatim.openstreetmap.org "
            "https://*.mongodb.net",
            # Workers: self (service worker)
            "worker-src 'self'",
            # Manifests: self
            "manifest-src 'self'",
            # Frames: none
            "frame-src 'none'",
            # Objects: none (no Flash etc.)
            "object-src 'none'",
            # Base URI restriction
            "base-uri 'self'",
            # Form actions: self only
            "form-action 'self'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_parts)

        # Prevent MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Clickjacking protection
        response.headers["X-Frame-Options"] = "DENY"

        # Referrer policy — no referrer for cross-origin requests
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy — only grant APIs ProELD actually uses
        response.headers["Permissions-Policy"] = (
            "geolocation=(self), "       # GPS — needed for location
            "camera=(), "                # not needed
            "microphone=(), "            # not needed
            "payment=(), "               # not needed
            "usb=(), "                   # not needed (OBD-II future: add 'self')
            "bluetooth=()"               # not needed yet
        )

        # Remove server fingerprint headers (MutableHeaders uses del, not pop)
        if "server" in response.headers:
            del response.headers["server"]
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]

        return response