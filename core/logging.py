"""
core/logging.py  –  Phase 2
Structured logging via structlog.
Import configure_logging() and call it once at startup.
All modules then use: log = structlog.get_logger(__name__)
"""
import logging
import structlog
from .config import settings


def configure_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_json:
        # Machine-readable JSON for production / log aggregators (Datadog, ELK)
        renderer = structlog.processors.JSONRenderer()
    else:
        # Human-readable coloured output for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Silence noisy libraries
    for lib in ("pymongo", "motor", "httpx", "asyncio"):
        logging.getLogger(lib).setLevel(logging.WARNING)