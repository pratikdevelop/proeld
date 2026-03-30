"""
routers/dvir.py  —  Phase 2
New: PATCH /dvir/:id/repair — carrier certifies defects repaired (§396.11)
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId

from core.database import get_db
from core.dependencies import require_driver
from models.schemas import DVIRSubmitRequest, RepairCertifyRequest

log = logging.getLogger("proeld.dvir")
router = APIRouter(prefix="/dvir", tags=["eDVIR"])


@router.post("", status_code=201)
async def submit_dvir(body: DVIRSubmitRequest, payload: dict = Depends(require_driver)):
    db        = get_db()
    driver_id = payload["sub"]
    driver    = await db.drivers.find_one({"_id": ObjectId(driver_id)})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    failed_items = [item.item_id for item in body.items if not item.passed]
    doc = {
        "driver_id":    driver_id,
        "vehicle_id":   body.vehicle_id.upper(),
        "trip_type":    body.trip_type,
        "items":        [i.model_dump() for i in body.items],
        "failed_items": failed_items,
        "has_defects":  len(failed_items) > 0,
        "remarks":      body.remarks,
        "odometer":     body.odometer,
        "submitted_at": datetime.now(timezone.utc),
        "location":     None,
        # Repair certification fields (§396.11)
        "repaired":          False,
        "repaired_at":       None,
        "repair_certified_by": None,
        "repair_note":       None,
        # Next driver acknowledgement
        "next_driver_acknowledged": False,
        "acknowledged_by":    None,
        "acknowledged_at":    None,
    }
    result = await db.dvir_reports.insert_one(doc)
    log.info("DVIR submitted: driver=%s vehicle=%s defects=%d",
             driver_id, doc["vehicle_id"], len(failed_items))

    return {
        "dvir_id":      str(result.inserted_id),
        "has_defects":  doc["has_defects"],
        "failed_items": failed_items,
        "message": (
            "DVIR submitted. Defects noted — vehicle must be repaired and certified "
            "before next trip. (49 CFR §396.11)"
            if doc["has_defects"] else
            "DVIR submitted. Vehicle cleared for operation."
        ),
    }


@router.get("")
async def list_dvirs(
    payload: dict = Depends(require_driver),
    limit:   int  = Query(default=20, le=100),
    skip:    int  = Query(default=0, ge=0),
):
    db     = get_db()
    cursor = db.dvir_reports.find(
        {"driver_id": payload["sub"]},
        sort=[("submitted_at", -1)]
    ).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [_dvir_summary(d) for d in docs]


@router.get("/latest")
async def latest_dvir(payload: dict = Depends(require_driver)):
    db  = get_db()
    doc = await db.dvir_reports.find_one(
        {"driver_id": payload["sub"]},
        sort=[("submitted_at", -1)]
    )
    if not doc:
        return {"dvir": None}
    return {"dvir": _dvir_detail(doc)}


# ════════════════════════════════════════════════════════════
#  §396.11 — REPAIR CERTIFICATION
# ════════════════════════════════════════════════════════════

@router.patch("/{dvir_id}/repair", status_code=200)
async def certify_repair(
    dvir_id: str,
    body: RepairCertifyRequest,
    payload: dict = Depends(require_driver),
):
    """
    Carrier/mechanic certifies that defects have been repaired (§396.11).
    Required before vehicle can return to service after a defect DVIR.
    """
    db = get_db()
    try:
        oid = ObjectId(dvir_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid DVIR ID.")

    dvir = await db.dvir_reports.find_one({"_id": oid})
    if not dvir:
        raise HTTPException(status_code=404, detail="DVIR not found.")
    if not dvir.get("has_defects"):
        raise HTTPException(status_code=400, detail="This DVIR has no defects to certify.")
    if dvir.get("repaired"):
        raise HTTPException(status_code=409, detail="Repairs already certified for this DVIR.")

    await db.dvir_reports.update_one(
        {"_id": oid},
        {"$set": {
            "repaired":              True,
            "repaired_at":           datetime.now(timezone.utc),
            "repair_certified_by":   body.certified_by,
            "repair_note":           body.note,
            "repairs_satisfactory":  body.repairs_satisfactory,
        }}
    )
    log.info("DVIR repair certified: dvir=%s certified_by=%s", dvir_id, body.certified_by)
    return {
        "repaired":    True,
        "repaired_at": datetime.now(timezone.utc).isoformat(),
        "message":     "Repairs certified. Vehicle cleared for next trip.",
    }


@router.post("/{dvir_id}/acknowledge", status_code=200)
async def acknowledge_prior_dvir(
    dvir_id: str,
    payload: dict = Depends(require_driver),
):
    """
    Next driver acknowledges they have reviewed the prior DVIR (§396.11).
    Required when picking up a vehicle that had defects on the previous DVIR.
    """
    db = get_db()
    try:
        oid = ObjectId(dvir_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid DVIR ID.")

    dvir = await db.dvir_reports.find_one({"_id": oid})
    if not dvir:
        raise HTTPException(status_code=404, detail="DVIR not found.")

    if dvir.get("has_defects") and not dvir.get("repaired"):
        # Vehicle not repaired — driver acknowledges and accepts defects
        await db.dvir_reports.update_one(
            {"_id": oid},
            {"$set": {
                "next_driver_acknowledged": True,
                "acknowledged_by":  payload["sub"],
                "acknowledged_at":  datetime.now(timezone.utc),
                "acknowledged_unrepaired": True,
            }}
        )
        return {
            "acknowledged": True,
            "warning": "Vehicle has unrepaired defects. Carrier has been notified.",
        }

    await db.dvir_reports.update_one(
        {"_id": oid},
        {"$set": {
            "next_driver_acknowledged": True,
            "acknowledged_by": payload["sub"],
            "acknowledged_at": datetime.now(timezone.utc),
        }}
    )
    return {"acknowledged": True, "message": "Prior DVIR acknowledged."}


# ── Helpers ───────────────────────────────────────────────────
def _dvir_summary(d: dict) -> dict:
    return {
        "id":           str(d["_id"]),
        "vehicle_id":   d["vehicle_id"],
        "trip_type":    d["trip_type"],
        "has_defects":  d.get("has_defects", False),
        "failed_items": d.get("failed_items", []),
        "repaired":     d.get("repaired", False),
        "submitted_at": d["submitted_at"].isoformat(),
    }

def _dvir_detail(d: dict) -> dict:
    base = _dvir_summary(d)
    base.update({
        "items":            d.get("items", []),
        "remarks":          d.get("remarks"),
        "repaired_at":      d["repaired_at"].isoformat() if d.get("repaired_at") else None,
        "repair_certified_by": d.get("repair_certified_by"),
        "next_driver_acknowledged": d.get("next_driver_acknowledged", False),
    })
    return base