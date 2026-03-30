"""
main.py  —  ProELD v3.2  (Phase 3: Security hardening)
New in this version:
  - Security headers middleware (HSTS, CSP, X-Frame-Options, etc.)
  - Secrets validation at startup — crashes fast if JWT_SECRET missing in prod
  - CORS tightened — uses ALLOWED_ORIGINS env var in production
  - /docs and /redoc disabled in production
  - Server fingerprint headers removed
  - Geocoder references cleaned up (Nominatim only)
"""
import logging
import os
import asyncio
import random
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from core.config import settings
from core.database import connect_db, close_db
from core.logging import configure_logging
from core.ratelimit import limiter
from core.errors import register_error_handlers
from core.security_headers import SecurityHeadersMiddleware
from services.geocoder import distance_miles, close_http_client
from routers import auth, hos, dot, dvir

# ── Structured logging ───────────────────────────────────────
configure_logging()
log = logging.getLogger("proeld.main")

# ── FMCSA HOS constants (49 CFR Part 395) ───────────────────
AVG_SPEED_MPH  = 65
DRIVE_LIMIT    = 11
DUTY_WINDOW    = 14
BREAK_REQ_AT   = 8
BREAK_DURATION = 0.5
REST_REQ       = 10
WEEKLY_LIMIT_7 = 60
WEEKLY_LIMIT_8 = 70

# ── Lifespan ─────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate secrets before accepting any traffic
    settings.validate_production_secrets()
    log.info("ProELD v%s starting [%s]", settings.app_version, settings.app_env)
    await connect_db()
    log.info("Geocoder: Nominatim (OpenStreetMap, free, no API key)")
    yield
    await close_http_client()
    await close_db()
    log.info("ProELD shutdown complete")


# ── App — disable docs in production ─────────────────────────
app = FastAPI(
    title       = "ProELD Driver Tablet API",
    version     = settings.app_version,
    description = "FMCSA-compliant ELD — 49 CFR Part 395",
    lifespan    = lifespan,
    docs_url    = None if settings.app_env == "production" else "/docs",
    redoc_url   = None if settings.app_env == "production" else "/redoc",
    openapi_url = None if settings.app_env == "production" else "/openapi.json",
)

# ── Static files ─────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

@app.get("/sw.js", include_in_schema=False)
async def service_worker_root():
    return FileResponse(
        os.path.join(_static_dir, "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )

# ── Middleware (order matters: outermost = last added) ────────
# 1. Security headers — outermost, wraps everything
app.add_middleware(SecurityHeadersMiddleware)

# 2. Rate limiting
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# 3. CORS — tightened in production
app.add_middleware(
    CORSMiddleware,
    allow_origins     = settings.cors_origins,
    allow_credentials = True,
    allow_methods     = ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers     = ["Authorization", "Content-Type", "Accept"],
    expose_headers    = ["X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# ── Error handlers ────────────────────────────────────────────
register_error_handlers(app)

# ── Routers ───────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(hos.router)
app.include_router(dot.router)
app.include_router(dvir.router)

# ── Templates ────────────────────────────────────────────────
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Health ────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    from core.database import get_db
    db = get_db()
    try:
        await db.command("ping")
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status":    "ok" if db_ok else "degraded",
        "version":   settings.app_version,
        "env":       settings.app_env,
        "database":  "connected" if db_ok else "unreachable",
        "geocoder":  "Nominatim (OpenStreetMap)",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── WebSocket Telemetry ───────────────────────────────────────
@app.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket):
    await websocket.accept()
    log.info("Telemetry WS connected: %s", websocket.client)

    speed = 0.0; rpm = 700; fuel_pct = round(random.uniform(30, 90), 1)
    engine_on = False; odometer = round(random.uniform(50000, 250000), 1)
    coolant_f = 180.0

    try:
        while True:
            if not engine_on and random.random() > 0.88:
                engine_on = True
            if engine_on:
                delta    = random.uniform(-4, 9) if speed < 60 else random.uniform(-8, 2)
                speed    = max(0.0, min(speed + delta, 75.0))
                if speed < 1 and random.random() > 0.7:
                    engine_on = False
                rpm       = int(800 + speed * 22 + random.randint(-100, 100))
                coolant_f = round(180 + speed * 0.2 + random.uniform(-2, 2), 1)
                fuel_pct  = max(5.0, fuel_pct - 0.015)
                odometer += speed * (2 / 3600)
            else:
                speed = 0.0; rpm = 700

            await websocket.send_json({
                "speed":     round(speed, 1),
                "rpm":       rpm,
                "engine_on": engine_on,
                "fuel_pct":  round(fuel_pct, 1),
                "coolant_f": coolant_f,
                "odometer":  round(odometer, 1),
                "timestamp": datetime.utcnow().isoformat(),
            })
            await asyncio.sleep(2)
    except (WebSocketDisconnect, Exception) as e:
        log.info("Telemetry WS disconnected: %s", e)


# ── Trip Planner ─────────────────────────────────────────────
@app.post("/calculate", tags=["Trip Planner"])
async def calculate(
    current_loc: str   = Form(..., max_length=200),
    pickup_loc:  str   = Form(..., max_length=200),
    dropoff_loc: str   = Form(..., max_length=200),
    cycle_used:  float = Form(default=0.0, ge=0, le=70),
    cycle_type:  int   = Form(default=8),
):
    if cycle_type not in (7, 8):
        cycle_type = 8
    weekly_limit = WEEKLY_LIMIT_8 if cycle_type == 8 else WEEKLY_LIMIT_7

    (dist_pickup,  start_c,  pickup_c), \
    (dist_dropoff, _,        dropoff_c) = await asyncio.gather(
        distance_miles(current_loc, pickup_loc),
        distance_miles(pickup_loc,  dropoff_loc),
    )
    total_dist = dist_pickup + dist_dropoff

    if total_dist <= 0:
        return JSONResponse({"error": "Could not resolve locations."}, status_code=400)

    events: list[dict] = []
    cur_time = 0.0; drv_today = 0.0; drv_break = 0.0
    duty_start = 0.0; weekly_used = cycle_used; remaining = total_dist

    def _add(status: str, duration: float, label: str = "") -> None:
        nonlocal cur_time
        duration = round(max(0.0, duration), 2)
        if duration <= 0:
            return
        h, m = int(cur_time % 24), int((cur_time % 1) * 60)
        events.append({"status": status, "duration": duration,
                        "label": label, "timestamp": f"{h:02d}:{m:02d}"})
        cur_time += duration

    _add("On-Duty", 1.0, f"Loading at {pickup_loc}")
    weekly_used += 1.0

    for _ in range(60):
        if remaining <= 0.5:
            break
        weekly_avail = weekly_limit - weekly_used
        if weekly_avail <= 0:
            _add("Off-Duty", 34.0, "34-Hr Restart (§395.3(c))")
            weekly_used = drv_today = drv_break = 0.0
            duty_start = cur_time
            continue

        can_drive = max(0.0, min(
            DRIVE_LIMIT  - drv_today,
            DUTY_WINDOW  - (cur_time - duty_start),
            BREAK_REQ_AT - drv_break,
            weekly_avail,
        ))

        if can_drive <= 0.01:
            if drv_today >= DRIVE_LIMIT or (cur_time - duty_start) >= DUTY_WINDOW:
                _add("Off-Duty", REST_REQ, "10-Hr Rest (§395.3(a)(1))")
                drv_today = drv_break = 0.0
                duty_start = cur_time
            else:
                _add("Off-Duty", BREAK_DURATION, "30-Min Break (§395.3(a)(3)(ii))")
                drv_break = 0.0
            continue

        drive_hrs = round(min(can_drive, remaining / AVG_SPEED_MPH), 2)
        if drive_hrs > 0:
            miles = drive_hrs * AVG_SPEED_MPH
            _add("Driving", drive_hrs, f"En route ({int(miles)} mi)")
            remaining  -= miles; drv_today += drive_hrs
            drv_break  += drive_hrs; weekly_used += drive_hrs

        if drv_break >= BREAK_REQ_AT and remaining > 0.5:
            _add("Off-Duty", BREAK_DURATION, "30-Min Break (§395.3(a)(3)(ii))")
            drv_break = 0.0

    _add("On-Duty", 1.0, f"Unloading at {dropoff_loc}")
    drv_hrs   = round(sum(e["duration"] for e in events if e["status"] == "Driving"), 2)
    total_hrs = round(sum(e["duration"] for e in events), 2)

    log.info("Trip calculated: %s → %s | %.1f mi, %.2f hrs, %d events",
             pickup_loc, dropoff_loc, total_dist, drv_hrs, len(events))

    return {
        "total_miles": round(total_dist, 1),
        "timeline":    events,
        "coords":      [
            list(start_c)   if start_c   else None,
            list(pickup_c)  if pickup_c  else None,
            list(dropoff_c) if dropoff_c else None,
        ],
        "summary": {"driving_hours": drv_hrs, "total_hours": total_hrs,
                    "stops": sum(1 for e in events if e["status"] == "Off-Duty")},
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000,
                reload=(settings.app_env == "development"))