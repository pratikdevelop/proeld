"""
services/hos.py
Server-side HOS calculation engine.

Reads real duty_events from MongoDB and computes live clock values.
This is the source of truth — the frontend only DISPLAYS what this returns.

FMCSA references throughout: 49 CFR Part 395
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

from models.schemas import HOSState, DutyEventDoc

logger = logging.getLogger("proeld.hos")

# ── FMCSA Constants ─────────────────────────────────────────
DRIVE_LIMIT_HRS    = 11.0   # §395.3(a)(3)(i)
DUTY_WINDOW_HRS    = 14.0   # §395.3(a)(2)
BREAK_REQUIRED_HRS =  8.0   # §395.3(a)(3)(ii) – 30-min break after 8 cumulative drive hrs
REST_REQUIRED_HRS  = 10.0   # §395.3(a)(1)     – required off-duty before new window
RESTART_HRS        = 34.0   # §395.3(c)        – 34-hr restart
WEEKLY_7DAY_HRS    = 60.0   # §395.3(b)(1)
WEEKLY_8DAY_HRS    = 70.0   # §395.3(b)(2)

OFF_STATUSES = {"Off-Duty", "Sleeper"}


async def calculate_hos_state(driver_id: str, db: AsyncIOMotorDatabase) -> HOSState:
    """
    Fetches the driver's events from MongoDB and calculates all live HOS clocks.
    Returns an HOSState with remaining seconds for each limit.
    """
    driver = await db.drivers.find_one({"_id": driver_id})
    cycle_hrs = WEEKLY_8DAY_HRS if (not driver or driver.get("cycle_type", 8) == 8) else WEEKLY_7DAY_HRS
    cycle_days = 8 if cycle_hrs == WEEKLY_8DAY_HRS else 7

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=cycle_days)

    # Fetch events in the rolling window, sorted oldest first
    cursor = db.duty_events.find(
        {"driver_id": driver_id, "started_at": {"$gte": window_start}},
        sort=[("started_at", 1)]
    )
    events = await cursor.to_list(length=1000)

    # ── Walk the event list forward ──────────────────────────
    drive_hrs_today        = 0.0
    duty_window_start_time: Optional[datetime] = None
    drive_since_break      = 0.0
    weekly_used_hrs        = 0.0
    off_duty_consecutive_secs = 0

    current_status: Optional[str] = None
    last_event_end: Optional[datetime] = None

    for ev in events:
        started = ev["started_at"]
        if isinstance(started, str):
            started = datetime.fromisoformat(started)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)

        ended = ev.get("ended_at") or now
        if isinstance(ended, str):
            ended = datetime.fromisoformat(ended)
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=timezone.utc)

        duration_hrs = (ended - started).total_seconds() / 3600.0
        status = ev["status"]
        current_status = status

        if status in OFF_STATUSES:
            off_duty_consecutive_secs += (ended - started).total_seconds()
            # A new duty window begins after 10+ consecutive hrs off
            if off_duty_consecutive_secs >= REST_REQUIRED_HRS * 3600:
                # Reset daily clocks
                drive_hrs_today    = 0.0
                drive_since_break  = 0.0
                duty_window_start_time = None
        else:
            off_duty_consecutive_secs = 0  # any on-duty/driving breaks the streak

            if status == "Driving":
                drive_hrs_today   += duration_hrs
                drive_since_break += duration_hrs
                weekly_used_hrs   += duration_hrs
                # Start the 14-hr window on first active event of the day
                if duty_window_start_time is None:
                    duty_window_start_time = started

            elif status == "On-Duty":
                weekly_used_hrs += duration_hrs
                if duty_window_start_time is None:
                    duty_window_start_time = started

    # ── Compute remaining values ─────────────────────────────
    drive_remaining   = max(0.0, DRIVE_LIMIT_HRS   - drive_hrs_today)
    break_remaining   = max(0.0, BREAK_REQUIRED_HRS - drive_since_break)
    weekly_remaining  = max(0.0, cycle_hrs           - weekly_used_hrs)

    if duty_window_start_time:
        elapsed_window = (now - duty_window_start_time).total_seconds() / 3600.0
        duty_window_remaining = max(0.0, DUTY_WINDOW_HRS - elapsed_window)
    else:
        duty_window_remaining = DUTY_WINDOW_HRS  # window hasn't started

    restart_eligible = off_duty_consecutive_secs >= RESTART_HRS * 3600

    return HOSState(
        driver_id                   = driver_id,
        cycle_type                  = int(cycle_hrs),
        drive_remaining_secs        = int(drive_remaining * 3600),
        duty_window_remaining_secs  = int(duty_window_remaining * 3600),
        break_remaining_secs        = int(break_remaining * 3600),
        weekly_remaining_secs       = int(weekly_remaining * 3600),
        off_duty_consecutive_secs   = int(off_duty_consecutive_secs),
        restart_eligible            = restart_eligible,
        current_status              = current_status,
        calculated_at               = now,
    )


async def open_duty_event(
    driver_id: str,
    vehicle_id: str,
    status: str,
    origin: str,
    location: Optional[str],
    client_time: Optional[datetime],
    db: AsyncIOMotorDatabase,
) -> str:
    """
    Closes any currently open event for this driver, then inserts a new one.
    Returns the new event's inserted_id as string.
    """
    now = datetime.now(timezone.utc)
    event_time = client_time or now

    # Close the last open event
    await db.duty_events.update_many(
        {"driver_id": driver_id, "ended_at": None},
        {"$set": {
            "ended_at":    event_time,
            "duration_hrs": None,  # will be computed below
        }}
    )

    # Compute duration for the event we just closed
    last = await db.duty_events.find_one(
        {"driver_id": driver_id, "ended_at": {"$ne": None}},
        sort=[("started_at", -1)]
    )
    if last and last.get("ended_at") and last.get("started_at"):
        s = last["started_at"]
        e = last["ended_at"]
        if isinstance(s, str): s = datetime.fromisoformat(s)
        if isinstance(e, str): e = datetime.fromisoformat(e)
        dur = round((e - s).total_seconds() / 3600, 4)
        await db.duty_events.update_one(
            {"_id": last["_id"]},
            {"$set": {"duration_hrs": dur}}
        )

    # Insert new open event
    doc = {
        "driver_id":  driver_id,
        "vehicle_id": vehicle_id,
        "status":     status,
        "started_at": event_time,
        "ended_at":   None,
        "duration_hrs": None,
        "location":   location,
        "origin":     origin,
        "certified":  False,
        "created_at": now,
    }
    result = await db.duty_events.insert_one(doc)
    logger.info(f"[HOS] driver={driver_id} new_status={status} origin={origin}")
    return str(result.inserted_id)