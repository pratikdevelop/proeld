"""
routers/auth.py  –  Phase 2
slowapi requires `response: Response` param on every @limiter.limit() route.
"""
import logging
from datetime import datetime, timezone, timedelta
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from bson import ObjectId

from core.database import get_db
from core.dependencies import require_driver
from core.security import hash_password, verify_password, create_access_token
from core.config import settings
from core.ratelimit import limiter
from models.schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    RefreshRequest, DOTPinSetRequest, DriverPublic,
)

log = logging.getLogger("proeld.auth")
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, response: Response, body: RegisterRequest):
    db = get_db()
    if await db.drivers.find_one({"email": body.email.lower()}):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    doc = {
        "full_name":     body.full_name,
        "email":         body.email.lower(),
        "password_hash": hash_password(body.password),
        "license_no":    body.license_no,
        "vehicle_id":    body.vehicle_id,
        "carrier_id":    body.carrier_id,
        "cycle_type":    body.cycle_type,
        "dot_pin_hash":  "",
        "created_at":    datetime.now(timezone.utc),
        "is_active":     True,
    }
    result    = await db.drivers.insert_one(doc)
    driver_id = str(result.inserted_id)
    log.info("Driver registered: %s", driver_id)

    access_token  = create_access_token(driver_id)
    refresh_token = token_urlsafe(48)
    await db.refresh_tokens.insert_one({
        "driver_id":  driver_id,
        "token":      refresh_token,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        "created_at": datetime.now(timezone.utc),
    })
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, response: Response, body: LoginRequest):
    db     = get_db()
    driver = await db.drivers.find_one({"email": body.email.lower()})

    if not driver or not verify_password(body.password, driver["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not driver.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    driver_id     = str(driver["_id"])
    access_token  = create_access_token(driver_id)
    refresh_token = token_urlsafe(48)

    await db.refresh_tokens.insert_one({
        "driver_id":  driver_id,
        "token":      refresh_token,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        "created_at": datetime.now(timezone.utc),
    })
    log.info("Driver logged in: %s", driver_id)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh_token(request: Request, response: Response, body: RefreshRequest):
    db     = get_db()
    record = await db.refresh_tokens.find_one({"token": body.refresh_token})

    if not record:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")
    if record["expires_at"].replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        await db.refresh_tokens.delete_one({"_id": record["_id"]})
        raise HTTPException(status_code=401, detail="Refresh token expired. Please log in again.")

    await db.refresh_tokens.delete_one({"_id": record["_id"]})
    driver_id   = record["driver_id"]
    new_access  = create_access_token(driver_id)
    new_refresh = token_urlsafe(48)

    await db.refresh_tokens.insert_one({
        "driver_id":  driver_id,
        "token":      new_refresh,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        "created_at": datetime.now(timezone.utc),
    })
    log.info("Tokens rotated for: %s", driver_id)
    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest):
    db     = get_db()
    result = await db.refresh_tokens.delete_one({"token": body.refresh_token})
    log.info("Logout: deleted %d token(s)", result.deleted_count)


@router.get("/me", response_model=DriverPublic)
async def get_me(payload: dict = Depends(require_driver)):
    db     = get_db()
    driver = await db.drivers.find_one({"_id": ObjectId(payload["sub"])})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    return DriverPublic(
        id=         str(driver["_id"]),
        full_name=  driver["full_name"],
        email=      driver["email"],
        license_no= driver["license_no"],
        vehicle_id= driver["vehicle_id"],
        carrier_id= driver.get("carrier_id"),
        cycle_type= driver.get("cycle_type", 8),
    )


@router.post("/set-dot-pin", status_code=200)
@limiter.limit("5/minute")
async def set_dot_pin(
    request: Request,
    response: Response,
    body: DOTPinSetRequest,
    payload: dict = Depends(require_driver),
):
    db     = get_db()
    driver = await db.drivers.find_one({"_id": ObjectId(payload["sub"])})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    if not verify_password(body.current_password, driver["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    await db.drivers.update_one(
        {"_id": driver["_id"]},
        {"$set": {"dot_pin_hash": hash_password(body.new_pin)}},
    )
    log.info("DOT PIN updated for: %s", payload["sub"])
    return {"message": "DOT PIN updated successfully."}