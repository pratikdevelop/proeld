"""
models/schemas.py  —  Phase 3 (Input sanitization hardening)
All inputs validated, stripped of dangerous chars, length-bounded.
"""
from __future__ import annotations
import re
import html as html_lib
from datetime import datetime, timezone
from typing import Literal, Optional, List
from pydantic import BaseModel, Field, field_validator, EmailStr
from bson import ObjectId


# ── Sanitization helpers ─────────────────────────────────────
def _strip(v: str) -> str:
    """Strip whitespace and HTML-encode dangerous chars."""
    return html_lib.escape(v.strip())

def _alphanum_dash(v: str, field: str) -> str:
    """Allow only letters, numbers, spaces, hyphens, underscores."""
    cleaned = re.sub(r"[^\w\s\-]", "", v.strip())
    if not cleaned:
        raise ValueError(f"{field} contains no valid characters.")
    return cleaned

def _no_script(v: str) -> str:
    """Block obvious script injection patterns."""
    dangerous = ["<script", "javascript:", "onerror=", "onload=", "eval("]
    lower = v.lower()
    for pattern in dangerous:
        if pattern in lower:
            raise ValueError("Input contains disallowed content.")
    return v.strip()


# ── ObjectId helper ──────────────────────────────────────────
class PyObjectId(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, str) and ObjectId.is_valid(v):
            return v
        raise ValueError(f"Invalid ObjectId: {v!r}")


# ════════════════════════════════════════════════════════════
#  AUTH
# ════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    full_name:  str = Field(..., min_length=2, max_length=100)
    email:      EmailStr
    password:   str = Field(..., min_length=8, max_length=72)
    license_no: str = Field(..., min_length=4, max_length=30)
    vehicle_id: str = Field(..., min_length=2, max_length=30)
    carrier_id: Optional[str] = Field(None, max_length=50)
    cycle_type: Literal[7, 8] = 8

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = _no_script(v)
        if not re.match(r"^[\w\s\-'.]+$", v):
            raise ValueError("Full name contains invalid characters.")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter.")
        return v

    @field_validator("license_no", "vehicle_id")
    @classmethod
    def clean_ids(cls, v: str) -> str:
        v = _no_script(v)
        cleaned = re.sub(r"[^\w\-]", "", v.strip()).upper()
        if not cleaned:
            raise ValueError("Field contains no valid characters.")
        return cleaned

    @field_validator("carrier_id")
    @classmethod
    def clean_carrier(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return re.sub(r"[^\w\-]", "", v.strip()).upper() or None


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str = Field(..., min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10, max_length=200)


# ════════════════════════════════════════════════════════════
#  DRIVER
# ════════════════════════════════════════════════════════════

class DriverDoc(BaseModel):
    id:            Optional[str] = Field(None, alias="_id")
    full_name:     str
    email:         str
    password_hash: str
    license_no:    str
    vehicle_id:    str
    carrier_id:    Optional[str] = None
    cycle_type:    Literal[7, 8] = 8
    dot_pin_hash:  str = ""
    created_at:    datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active:     bool = True
    model_config   = {"populate_by_name": True}


class DriverPublic(BaseModel):
    id:         str
    full_name:  str
    email:      str
    license_no: str
    vehicle_id: str
    carrier_id: Optional[str]
    cycle_type: int


# ════════════════════════════════════════════════════════════
#  DUTY EVENTS
# ════════════════════════════════════════════════════════════

DutyStatus  = Literal["Off-Duty", "Sleeper", "Driving", "On-Duty"]
EventOrigin = Literal["manual", "auto_motion", "sync", "system"]


class DutyEventDoc(BaseModel):
    id:           Optional[str] = Field(None, alias="_id")
    driver_id:    str
    vehicle_id:   str
    status:       DutyStatus
    started_at:   datetime
    ended_at:     Optional[datetime] = None
    duration_hrs: Optional[float]    = None
    location:     Optional[str]      = None
    origin:       EventOrigin        = "manual"
    certified:    bool               = False
    created_at:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_config  = {"populate_by_name": True}


class AppendEventRequest(BaseModel):
    status:    DutyStatus
    location:  Optional[str] = Field(None, max_length=200)
    origin:    EventOrigin   = "manual"
    timestamp: Optional[datetime] = None

    @field_validator("location")
    @classmethod
    def clean_location(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = _no_script(v)
        return v[:200].strip() or None


class DutyEventPublic(BaseModel):
    id:           str
    status:       str
    started_at:   datetime
    ended_at:     Optional[datetime]
    duration_hrs: Optional[float]
    location:     Optional[str]
    origin:       str
    certified:    bool


# ════════════════════════════════════════════════════════════
#  HOS STATE
# ════════════════════════════════════════════════════════════

class HOSState(BaseModel):
    driver_id:                  str
    cycle_type:                 int
    drive_remaining_secs:       int
    duty_window_remaining_secs: int
    break_remaining_secs:       int
    weekly_remaining_secs:      int
    off_duty_consecutive_secs:  int
    restart_eligible:           bool
    current_status:             Optional[str]
    calculated_at:              datetime


# ════════════════════════════════════════════════════════════
#  DVIR
# ════════════════════════════════════════════════════════════

class DVIRItem(BaseModel):
    item_id: str = Field(..., min_length=1, max_length=30,
                         pattern=r"^[a-z_]+$")
    passed:  bool
    note:    Optional[str] = Field(None, max_length=500)

    @field_validator("note")
    @classmethod
    def clean_note(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _no_script(v)[:500].strip() or None


class DVIRSubmitRequest(BaseModel):
    vehicle_id: str = Field(..., min_length=2, max_length=30)
    items:      List[DVIRItem] = Field(..., min_length=1, max_length=50)
    remarks:    Optional[str]  = Field(None, max_length=1000)
    odometer:   Optional[float] = Field(None, ge=0, le=10_000_000)
    trip_type:  Literal["pre_trip", "post_trip", "en_route"] = "post_trip"

    @field_validator("remarks")
    @classmethod
    def clean_remarks(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _no_script(v)[:1000].strip() or None


class DVIRDoc(BaseModel):
    id:           Optional[str] = Field(None, alias="_id")
    driver_id:    str
    vehicle_id:   str
    trip_type:    str
    items:        List[DVIRItem]
    remarks:      Optional[str]
    odometer:     Optional[float]
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    location:     Optional[str] = None
    model_config  = {"populate_by_name": True}


# ════════════════════════════════════════════════════════════
#  DOT INSPECTION
# ════════════════════════════════════════════════════════════

class DOTPinSetRequest(BaseModel):
    current_password: str = Field(..., min_length=1,  max_length=72)
    new_pin:          str = Field(..., min_length=4, max_length=8,
                                   pattern=r"^\d+$")


class DOTPinVerifyRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=8, pattern=r"^\d+$")


# ════════════════════════════════════════════════════════════
#  OFFLINE SYNC
# ════════════════════════════════════════════════════════════

class OfflineSyncPayload(BaseModel):
    events:    List[AppendEventRequest] = Field(..., max_length=500)
    device_id: Optional[str]           = Field(None, max_length=100)


# ════════════════════════════════════════════════════════════
#  PHASE 2 — NEW REQUEST SCHEMAS
# ════════════════════════════════════════════════════════════

class LogCertifyRequest(BaseModel):
    """Driver certifies a day's log (§395.8)."""
    signature:  str  = Field(..., min_length=2, max_length=100,
                              description="Driver's full name as electronic signature")
    amendment:  bool = False   # True if correcting a previously certified log
    note:       Optional[str] = Field(None, max_length=500)

    @field_validator("signature")
    @classmethod
    def clean_sig(cls, v: str) -> str:
        return _no_script(v)


class MalfunctionRequest(BaseModel):
    """Log an ELD malfunction or diagnostic event (§395.34)."""
    code:   str = Field(..., min_length=1, max_length=1,
                         description="FMCSA code: P E T L R S O D")
    note:   Optional[str] = Field(None, max_length=500)
    origin: Literal["auto", "manual"] = "manual"

    @field_validator("code")
    @classmethod
    def upper_code(cls, v: str) -> str:
        return v.upper()


class UnidentifiedClaimRequest(BaseModel):
    """Driver claims or rejects an unidentified driving event (§395.30)."""
    event_id: str = Field(..., min_length=24, max_length=24)
    action:   Literal["claim", "reject"]
    note:     Optional[str] = Field(None, max_length=500)


class RepairCertifyRequest(BaseModel):
    """Carrier/mechanic certifies DVIR defects repaired (§396.11)."""
    certified_by:          str  = Field(..., min_length=2, max_length=100)
    repairs_satisfactory:  bool = True
    note:                  Optional[str] = Field(None, max_length=500)

    @field_validator("certified_by")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return _no_script(v)