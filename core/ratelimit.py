"""
core/ratelimit.py  –  Phase 2
Centralized slowapi limiter instance.
Import `limiter` and apply @limiter.limit("N/minute") to route functions.
Attach limiter.state to app.state and register the exception handler in main.py.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Key function: rate-limit per IP address.
# In production behind a proxy, use a custom key_func that reads X-Forwarded-For.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],          # No default; we apply limits per-route
    headers_enabled=True,       # Adds RateLimit-* headers to responses
)