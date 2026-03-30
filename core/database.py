"""
core/database.py  —  Phase 2
Added indexes for new Phase 2 collections:
  log_certifications, eld_malfunctions
"""
import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from .config import settings

log = logging.getLogger("proeld.db")

_client: AsyncIOMotorClient | None = None
_db:     AsyncIOMotorDatabase | None = None


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised — call connect_db() first.")
    return _db


async def connect_db() -> None:
    global _client, _db
    log.info("Connecting to MongoDB at %s / db=%s", settings.mongo_uri, settings.mongo_db)
    _client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=6000)
    await _client.admin.command("ping")
    _db = _client[settings.mongo_db]
    log.info("MongoDB connected ✓")
    await _ensure_indexes(_db)
    log.info("MongoDB indexes ensured ✓")


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    from pymongo import ASCENDING, DESCENDING, IndexModel

    # drivers
    await db.drivers.create_indexes([
        IndexModel([("email", ASCENDING)], unique=True),
    ])

    # duty_events
    await db.duty_events.create_indexes([
        IndexModel([("driver_id", ASCENDING), ("started_at", DESCENDING)]),
        IndexModel([("driver_id", ASCENDING), ("ended_at",   ASCENDING)]),
        IndexModel([("vehicle_id", ASCENDING), ("driver_id", ASCENDING)]),
        IndexModel([("driver_id", ASCENDING), ("certified",  ASCENDING)]),
    ])

    # refresh_tokens
    await db.refresh_tokens.create_indexes([
        IndexModel([("token",     ASCENDING)], unique=True),
        IndexModel([("driver_id", ASCENDING)]),
        IndexModel([("expires_at",ASCENDING)], expireAfterSeconds=0),
    ])

    # dvir_reports
    await db.dvir_reports.create_indexes([
        IndexModel([("driver_id",  ASCENDING), ("submitted_at", DESCENDING)]),
        IndexModel([("vehicle_id", ASCENDING), ("submitted_at", DESCENDING)]),
        IndexModel([("has_defects",ASCENDING), ("repaired",     ASCENDING)]),
    ])

    # dot_pin_attempts
    await db.dot_pin_attempts.create_indexes([
        IndexModel([("driver_id", ASCENDING), ("timestamp", DESCENDING)]),
    ])

    # Phase 2 — log_certifications
    await db.log_certifications.create_indexes([
        IndexModel([("driver_id", ASCENDING), ("date", ASCENDING)], unique=True),
    ])

    # Phase 2 — eld_malfunctions
    await db.eld_malfunctions.create_indexes([
        IndexModel([("driver_id", ASCENDING), ("detected_at", DESCENDING)]),
        IndexModel([("driver_id", ASCENDING), ("resolved",    ASCENDING)]),
        IndexModel([("vehicle_id",ASCENDING), ("resolved",    ASCENDING)]),
    ])


async def close_db() -> None:
    global _client, _db
    if _client:
        _client.close()
        _client = _db = None
        log.info("MongoDB connection closed.")