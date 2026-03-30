"""
core/errors.py  –  Phase 2
Unified error response formatting using stdlib logging.
"""
import logging
import traceback

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi.errors import RateLimitExceeded

log = logging.getLogger("proeld.errors")


def _body(error: str, detail: str, status: int, fields: list | None = None) -> dict:
    b = {"error": error, "detail": detail, "status": status}
    if fields:
        b["fields"] = fields
    return b


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    fields = [
        {"field": " → ".join(str(l) for l in e["loc"] if l != "body"), "msg": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content=_body(
        "ValidationError", f"{len(fields)} field(s) failed validation.", 422, fields
    ))


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    names = {400:"BadRequest", 401:"Unauthorized", 403:"Forbidden",
             404:"NotFound", 409:"Conflict", 500:"InternalError"}
    return JSONResponse(
        status_code=exc.status_code,
        content=_body(names.get(exc.status_code, "HTTPError"), str(exc.detail), exc.status_code),
    )


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content=_body("RateLimitExceeded", f"Too many requests. Limit: {exc.limit}.", 429),
        headers={"Retry-After": "60"},
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled exception on %s %s: %s\n%s",
              request.method, request.url.path, exc, traceback.format_exc())
    return JSONResponse(status_code=500, content=_body(
        "InternalError", "An unexpected error occurred.", 500
    ))


def register_error_handlers(app) -> None:
    app.add_exception_handler(RequestValidationError,  validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException,  http_exception_handler)
    app.add_exception_handler(RateLimitExceeded,       rate_limit_handler)
    app.add_exception_handler(Exception,               unhandled_exception_handler)