"""
routers/hos.py  —  Phase 2
New endpoints:
  POST /hos/certify/{date}      — driver certifies a day's log  (§395.8)
  GET  /hos/history             — last 7 days summary            (§395.8(k))
  POST /hos/malfunction         — log an ELD malfunction code    (§395.34)
  GET  /hos/malfunctions        — list active malfunctions
  POST /hos/transfer            — generate DOT data-transfer package (§395.26)
  POST /hos/unidentified/claim  — driver claims unidentified driving (§395.30)
  GET  /hos/unidentified        — list unclaimed unidentified events
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
import logging

from core.database import get_db
from core.dependencies import require_driver
from models.schemas import (
    AppendEventRequest, HOSState,
    DutyEventPublic, OfflineSyncPayload,
    LogCertifyRequest, MalfunctionRequest,
    UnidentifiedClaimRequest,
)
from services.hos import calculate_hos_state, open_duty_event

log = logging.getLogger("proeld.hos")
router = APIRouter(prefix="/hos", tags=["Hours of Service"])


# ── Live HOS State ───────────────────────────────────────────
@router.get("/state", response_model=HOSState)
async def get_hos_state(payload: dict = Depends(require_driver)):
    db = get_db()
    return await calculate_hos_state(driver_id=payload["sub"], db=db)


# ── Append Duty Event ────────────────────────────────────────
@router.post("/event", status_code=201)
async def append_event(body: AppendEventRequest, payload: dict = Depends(require_driver)):
    db        = get_db()
    driver_id = payload["sub"]
    driver    = await db.drivers.find_one({"_id": ObjectId(driver_id)})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    event_id = await open_duty_event(
        driver_id=driver_id, vehicle_id=driver["vehicle_id"],
        status=body.status, origin=body.origin,
        location=body.location, client_time=body.timestamp, db=db,
    )
    hos = await calculate_hos_state(driver_id=driver_id, db=db)
    return {"event_id": event_id, "hos": hos}


# ── Events by Date ────────────────────────────────────────────
@router.get("/events/{date_str}", response_model=list[DutyEventPublic])
async def get_events_by_date(date_str: str, payload: dict = Depends(require_driver)):
    db = get_db()
    try:
        day_start = datetime.fromisoformat(date_str).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD.")
    day_end = day_start + timedelta(days=1)
    cursor = db.duty_events.find(
        {"driver_id": payload["sub"], "started_at": {"$gte": day_start, "$lt": day_end}},
        sort=[("started_at", 1)]
    )
    docs = await cursor.to_list(length=500)
    return [_to_public(d) for d in docs]


# ── Event History (paginated) ─────────────────────────────────
@router.get("/events", response_model=list[DutyEventPublic])
async def get_events(
    payload:   dict = Depends(require_driver),
    limit:     int  = Query(default=100, le=500),
    skip:      int  = Query(default=0, ge=0),
    from_date: str  = Query(default=None),
):
    db        = get_db()
    query: dict = {"driver_id": payload["sub"]}
    if from_date:
        try:
            dt = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
            query["started_at"] = {"$gte": dt}
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date.")
    cursor = db.duty_events.find(query, sort=[("started_at", -1)]).skip(skip).limit(limit)
    docs   = await cursor.to_list(length=limit)
    return [_to_public(d) for d in docs]


# ════════════════════════════════════════════════════════════
#  §395.8 — LOG CERTIFICATION
# ════════════════════════════════════════════════════════════

@router.post("/certify/{date_str}", status_code=200)
async def certify_log(
    date_str: str,
    body: LogCertifyRequest,
    payload: dict = Depends(require_driver),
):
    """
    Driver certifies that a specific day's log is complete and accurate.
    Required by FMCSA §395.8 — must be done for each day worked.
    Marks all events for that day as certified=True and stores certification record.
    """
    db        = get_db()
    driver_id = payload["sub"]

    try:
        day_start = datetime.fromisoformat(date_str).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD.")
    day_end = day_start + timedelta(days=1)

    # Check there are events to certify
    count = await db.duty_events.count_documents({
        "driver_id":  driver_id,
        "started_at": {"$gte": day_start, "$lt": day_end},
    })
    if count == 0:
        raise HTTPException(status_code=404, detail=f"No log events found for {date_str}.")

    # Mark all events certified
    result = await db.duty_events.update_many(
        {"driver_id": driver_id, "started_at": {"$gte": day_start, "$lt": day_end}},
        {"$set": {"certified": True}},
    )

    # Store the certification record
    await db.log_certifications.insert_one({
        "driver_id":    driver_id,
        "date":         date_str,
        "certified_at": datetime.now(timezone.utc),
        "signature":    body.signature,   # driver's typed name
        "events_count": count,
        "amendment":    body.amendment,   # True if correcting a prior cert
        "note":         body.note,
    })

    log.info("Log certified: driver=%s date=%s events=%d", driver_id, date_str, count)
    return {
        "certified":    True,
        "date":         date_str,
        "events_count": result.modified_count,
        "certified_at": datetime.now(timezone.utc).isoformat(),
        "message": f"Log for {date_str} certified. {result.modified_count} events marked.",
    }


# ════════════════════════════════════════════════════════════
#  §395.8(k) — 7-DAY HISTORY (must be on device at all times)
# ════════════════════════════════════════════════════════════

@router.get("/history")
async def get_7day_history(payload: dict = Depends(require_driver)):
    """
    Returns summary of last 7 days — required on device at all times (§395.8(k)).
    Used by the frontend for the weekly summary grid and DOT inspection display.
    """
    db        = get_db()
    driver_id = payload["sub"]
    now       = datetime.now(timezone.utc)
    days      = []

    for i in range(7):
        day_start = (now - timedelta(days=i)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = day_start + timedelta(days=1)

        cursor = db.duty_events.find(
            {"driver_id": driver_id, "started_at": {"$gte": day_start, "$lt": day_end}},
            sort=[("started_at", 1)]
        )
        events = await cursor.to_list(length=500)

        drive_hrs  = sum(e.get("duration_hrs", 0) or 0 for e in events if e["status"] == "Driving")
        duty_hrs   = sum(e.get("duration_hrs", 0) or 0 for e in events if e["status"] == "On-Duty")
        off_hrs    = sum(e.get("duration_hrs", 0) or 0 for e in events if e["status"] in ("Off-Duty","Sleeper"))
        certified  = all(e.get("certified", False) for e in events) if events else False

        # Check if this day has a certification record
        cert_rec = await db.log_certifications.find_one(
            {"driver_id": driver_id, "date": day_start.strftime("%Y-%m-%d")}
        )

        days.append({
            "date":          day_start.strftime("%Y-%m-%d"),
            "day_name":      day_start.strftime("%a"),
            "drive_hrs":     round(drive_hrs, 2),
            "duty_hrs":      round(duty_hrs, 2),
            "off_hrs":       round(off_hrs, 2),
            "total_on_hrs":  round(drive_hrs + duty_hrs, 2),
            "events_count":  len(events),
            "certified":     certified,
            "cert_record":   cert_rec is not None,
        })

    return {
        "driver_id":     driver_id,
        "days":          days,
        "total_drive_7": round(sum(d["drive_hrs"] for d in days), 2),
        "total_on_7":    round(sum(d["total_on_hrs"] for d in days), 2),
        "generated_at":  now.isoformat(),
    }


# ════════════════════════════════════════════════════════════
#  §395.34 — ELD MALFUNCTIONS & DIAGNOSTICS
# ════════════════════════════════════════════════════════════

# FMCSA §395.34 requires ELDs to detect and record 8 specific malfunction types
MALFUNCTION_CODES = {
    "P":  "Power compliance",
    "E":  "Engine synchronization compliance",
    "T":  "Timing compliance",
    "L":  "Positioning compliance (GPS)",
    "R":  "Data recording compliance",
    "S":  "Data transfer compliance",
    "O":  "Other ELD detected malfunction",
    "D":  "Data diagnostic event",
}

@router.post("/malfunction", status_code=201)
async def report_malfunction(
    body: MalfunctionRequest,
    payload: dict = Depends(require_driver),
):
    """
    Log an ELD malfunction or diagnostic event (§395.34).
    The ELD must detect, display, and record these automatically.
    Driver/carrier must resolve within 8 days or revert to paper logs.
    """
    db        = get_db()
    driver_id = payload["sub"]

    if body.code not in MALFUNCTION_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid malfunction code '{body.code}'. Valid: {list(MALFUNCTION_CODES.keys())}"
        )

    driver = await db.drivers.find_one({"_id": ObjectId(driver_id)})
    doc = {
        "driver_id":   driver_id,
        "vehicle_id":  driver.get("vehicle_id", "UNKNOWN") if driver else "UNKNOWN",
        "code":        body.code,
        "description": MALFUNCTION_CODES[body.code],
        "note":        body.note,
        "detected_at": datetime.now(timezone.utc),
        "resolved_at": None,
        "resolved":    False,
        "origin":      body.origin,   # "auto" (ELD detected) or "manual" (driver reported)
    }
    result = await db.eld_malfunctions.insert_one(doc)
    log.warning("ELD malfunction logged: driver=%s code=%s desc=%s",
                driver_id, body.code, MALFUNCTION_CODES[body.code])

    return {
        "malfunction_id": str(result.inserted_id),
        "code":           body.code,
        "description":    MALFUNCTION_CODES[body.code],
        "detected_at":    doc["detected_at"].isoformat(),
        "action_required": (
            "Notify carrier immediately. If not resolved within 8 days, "
            "revert to paper logs (§395.34(d))."
        ),
    }


@router.get("/malfunctions")
async def get_malfunctions(
    payload:    dict = Depends(require_driver),
    active_only: bool = Query(default=True),
):
    """List ELD malfunctions — active (unresolved) by default."""
    db    = get_db()
    query = {"driver_id": payload["sub"]}
    if active_only:
        query["resolved"] = False

    cursor = db.eld_malfunctions.find(query, sort=[("detected_at", -1)])
    docs   = await cursor.to_list(length=100)
    return [
        {
            "id":          str(d["_id"]),
            "code":        d["code"],
            "description": d["description"],
            "detected_at": d["detected_at"].isoformat(),
            "resolved":    d["resolved"],
            "resolved_at": d["resolved_at"].isoformat() if d.get("resolved_at") else None,
            "note":        d.get("note"),
        }
        for d in docs
    ]


@router.patch("/malfunctions/{malfunction_id}/resolve", status_code=200)
async def resolve_malfunction(
    malfunction_id: str,
    payload: dict = Depends(require_driver),
):
    """Mark an ELD malfunction as resolved."""
    db = get_db()
    try:
        oid = ObjectId(malfunction_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid malfunction ID.")

    result = await db.eld_malfunctions.update_one(
        {"_id": oid, "driver_id": payload["sub"]},
        {"$set": {"resolved": True, "resolved_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Malfunction not found.")
    return {"resolved": True, "resolved_at": datetime.now(timezone.utc).isoformat()}


# ════════════════════════════════════════════════════════════
#  §395.26 — DOT DATA TRANSFER
# ════════════════════════════════════════════════════════════

@router.post("/transfer")
async def generate_transfer_package(
    payload: dict = Depends(require_driver),
    days: int = Query(default=7, ge=1, le=8, description="Days of history to include"),
):
    """
    Generates a DOT-compliant data transfer package (§395.26).
    In production this would produce a USB/Bluetooth-transmittable file.
    For now returns structured JSON that a DOT officer can read on their device.
    """
    db        = get_db()
    driver_id = payload["sub"]
    now       = datetime.now(timezone.utc)
    since     = now - timedelta(days=days)

    driver = await db.drivers.find_one({"_id": ObjectId(driver_id)})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    # Collect all events
    cursor = db.duty_events.find(
        {"driver_id": driver_id, "started_at": {"$gte": since}},
        sort=[("started_at", 1)]
    )
    events = await cursor.to_list(length=5000)

    # Collect DVIRs
    dvir_cursor = db.dvir_reports.find(
        {"driver_id": driver_id, "submitted_at": {"$gte": since}},
        sort=[("submitted_at", -1)]
    )
    dvirs = await dvir_cursor.to_list(length=100)

    # Active malfunctions
    mal_cursor = db.eld_malfunctions.find(
        {"driver_id": driver_id, "resolved": False}
    )
    malfunctions = await mal_cursor.to_list(length=50)

    hos = await calculate_hos_state(driver_id=driver_id, db=db)

    package = {
        "transfer_type":   "DOT_INSPECTION",
        "generated_at":    now.isoformat(),
        "days_included":   days,
        "eld_identifier":  "ProELD-v3.2",
        "driver": {
            "name":        driver["full_name"],
            "license":     driver["license_no"],
            "vehicle_id":  driver["vehicle_id"],
            "carrier_id":  driver.get("carrier_id"),
        },
        "current_hos": {
            "status":              hos.current_status,
            "drive_remaining_hrs": round(hos.drive_remaining_secs / 3600, 2),
            "duty_window_hrs":     round(hos.duty_window_remaining_secs / 3600, 2),
            "weekly_remaining_hrs":round(hos.weekly_remaining_secs / 3600, 2),
        },
        "duty_events": [
            {
                "status":     e["status"],
                "started_at": e["started_at"].isoformat(),
                "ended_at":   e["ended_at"].isoformat() if e.get("ended_at") else None,
                "duration_hrs": e.get("duration_hrs"),
                "location":   e.get("location"),
                "origin":     e.get("origin"),
                "certified":  e.get("certified", False),
            }
            for e in events
        ],
        "dvir_reports": [
            {
                "submitted_at": d["submitted_at"].isoformat(),
                "vehicle_id":   d["vehicle_id"],
                "trip_type":    d["trip_type"],
                "has_defects":  d.get("has_defects", False),
                "failed_items": d.get("failed_items", []),
            }
            for d in dvirs
        ],
        "active_malfunctions": [
            {"code": m["code"], "description": m["description"],
             "detected_at": m["detected_at"].isoformat()}
            for m in malfunctions
        ],
    }
    log.info("DOT transfer package generated: driver=%s days=%d events=%d",
             driver_id, days, len(events))
    return package


# ════════════════════════════════════════════════════════════
#  §395.30 — UNIDENTIFIED DRIVER PROFILE
# ════════════════════════════════════════════════════════════

@router.get("/unidentified")
async def get_unidentified_events(payload: dict = Depends(require_driver)):
    """
    Returns driving events not yet assigned to any driver (§395.30).
    Drivers must review and claim or reject within 8 days.
    """
    db = get_db()
    driver = await db.drivers.find_one({"_id": ObjectId(payload["sub"])})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    # Unidentified events = same vehicle, no driver_id, within 8 days
    since  = datetime.now(timezone.utc) - timedelta(days=8)
    cursor = db.duty_events.find({
        "vehicle_id": driver.get("vehicle_id"),
        "driver_id":  "UNIDENTIFIED",
        "started_at": {"$gte": since},
    }, sort=[("started_at", -1)])
    docs = await cursor.to_list(length=200)
    return {
        "unidentified_count": len(docs),
        "events": [_to_public(d) for d in docs],
        "deadline_note": "§395.30 requires review within 8 days of the driving date.",
    }


@router.post("/unidentified/claim", status_code=200)
async def claim_unidentified(
    body: UnidentifiedClaimRequest,
    payload: dict = Depends(require_driver),
):
    """
    Driver claims or rejects an unidentified driving event (§395.30).
    Claimed events are re-assigned to this driver and included in their HOS.
    """
    db = get_db()
    try:
        oid = ObjectId(body.event_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid event ID.")

    event = await db.duty_events.find_one({"_id": oid, "driver_id": "UNIDENTIFIED"})
    if not event:
        raise HTTPException(status_code=404, detail="Unidentified event not found.")

    if body.action == "claim":
        await db.duty_events.update_one(
            {"_id": oid},
            {"$set": {
                "driver_id": payload["sub"],
                "origin":    "claimed",
                "claimed_at": datetime.now(timezone.utc),
                "claim_note": body.note,
            }}
        )
        log.info("Unidentified event claimed: driver=%s event=%s", payload["sub"], body.event_id)
        return {"action": "claimed", "event_id": body.event_id,
                "message": "Driving event added to your logs."}
    else:
        await db.duty_events.update_one(
            {"_id": oid},
            {"$set": {
                "driver_id":   "REJECTED",
                "rejected_by": payload["sub"],
                "rejected_at": datetime.now(timezone.utc),
                "reject_note": body.note,
            }}
        )
        return {"action": "rejected", "event_id": body.event_id,
                "message": "Event rejected and flagged for carrier review."}


# ── Offline Sync ──────────────────────────────────────────────
@router.post("/sync", status_code=200)
async def sync_offline(body: OfflineSyncPayload, payload: dict = Depends(require_driver)):
    db        = get_db()
    driver_id = payload["sub"]
    driver    = await db.drivers.find_one({"_id": ObjectId(driver_id)})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    inserted = skipped = 0
    for ev in sorted(body.events, key=lambda e: e.timestamp or datetime.min):
        event_time = ev.timestamp or datetime.now(timezone.utc)
        if await db.duty_events.find_one({"driver_id": driver_id, "started_at": event_time}):
            skipped += 1
            continue
        await open_duty_event(
            driver_id=driver_id, vehicle_id=driver["vehicle_id"],
            status=ev.status, origin="sync",
            location=ev.location, client_time=event_time, db=db,
        )
        inserted += 1

    return {"status": "ok", "inserted": inserted, "skipped": skipped, "device_id": body.device_id}


# ── Helper ────────────────────────────────────────────────────
def _to_public(d: dict) -> DutyEventPublic:
    return DutyEventPublic(
        id=str(d["_id"]), status=d["status"],
        started_at=d["started_at"], ended_at=d.get("ended_at"),
        duration_hrs=d.get("duration_hrs"), location=d.get("location"),
        origin=d.get("origin", "manual"), certified=d.get("certified", False),
    )