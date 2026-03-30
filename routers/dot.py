"""
routers/dot.py  –  Phase 2
"""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from bson import ObjectId

from core.database import get_db
from core.dependencies import require_driver
from core.security import verify_password
from core.ratelimit import limiter
from models.schemas import DOTPinVerifyRequest

log = logging.getLogger("proeld.dot")
router = APIRouter(prefix="/dot", tags=["DOT Inspection"])


@router.post("/verify-pin")
@limiter.limit("5/minute")
async def verify_dot_pin(
    request: Request,
    response: Response,
    body: DOTPinVerifyRequest,
    payload: dict = Depends(require_driver),
):
    db     = get_db()
    driver = await db.drivers.find_one({"_id": ObjectId(payload["sub"])})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    pin_hash = driver.get("dot_pin_hash", "")
    if not pin_hash:
        raise HTTPException(
            status_code=400,
            detail="No DOT PIN set. Please set one via POST /auth/set-dot-pin.",
        )

    if not verify_password(body.pin, pin_hash):
        await db.dot_pin_attempts.insert_one({
            "driver_id": payload["sub"],
            "success":   False,
            "ip":        request.client.host if request.client else "unknown",
            "timestamp": datetime.now(timezone.utc),
        })
        log.warning("DOT PIN failure for driver: %s", payload["sub"])
        raise HTTPException(status_code=401, detail="Incorrect PIN.")

    await db.dot_pin_attempts.insert_one({
        "driver_id": payload["sub"],
        "success":   True,
        "ip":        request.client.host if request.client else "unknown",
        "timestamp": datetime.now(timezone.utc),
    })
    log.info("DOT inspection unlocked for: %s", payload["sub"])
    return {"unlocked": True}


@router.get("/inspection")
async def get_inspection_data(payload: dict = Depends(require_driver)):
    from services.hos import calculate_hos_state
    db        = get_db()
    driver_id = payload["sub"]
    hos       = await calculate_hos_state(driver_id=driver_id, db=db)
    driver    = await db.drivers.find_one({"_id": ObjectId(driver_id)})

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    cursor   = db.duty_events.find(
        {"driver_id": driver_id, "started_at": {"$gte": week_ago}},
        sort=[("started_at", 1)],
    )
    events = await cursor.to_list(length=1000)
    return {
        "driver": {
            "full_name":  driver["full_name"] if driver else "Unknown",
            "license_no": driver.get("license_no", "") if driver else "",
            "vehicle_id": driver.get("vehicle_id", "") if driver else "",
        },
        "hos_state":         hos,
        "event_count_7days": len(events),
        "generated_at":      datetime.now(timezone.utc).isoformat(),
    }