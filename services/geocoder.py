"""
services/geocoder.py  –  Phase 2 (Nominatim only, no API key)

Uses Nominatim (OpenStreetMap) for both forward and reverse geocoding.
Nominatim is free, no key needed, but limited to ~1 req/sec per OSM policy.

To stay compliant:
  - A 1.1s delay is enforced between sequential forward geocode calls
  - asyncio.gather() is NOT used for forward geocodes (would violate rate limit)
  - A proper User-Agent is sent with every request

Public API (drop-in, same signatures as before):
    coords         = await geocode("Dallas, TX")         # → (lat, lng) | None
    city           = await reverse_geocode(32.78, -96.8) # → "Dallas, TX"
    miles, c1, c2  = await distance_miles("A", "B")      # → (float, tuple, tuple)
"""
import asyncio
import logging
from typing import Optional

from geopy.geocoders import Nominatim
from geopy.distance import geodesic

log = logging.getLogger("proeld.geocoder")

# Single Nominatim instance reused across all calls
_nom = Nominatim(
    user_agent="ProELD/3.1 (FMCSA ELD tablet; opensource)",
    timeout=10,
)

# OSM policy: max 1 request per second
_RATE_DELAY = 1.1   # seconds between sequential forward geocode calls
_last_geocode_time: float = 0.0


# ── Lifecycle (no-op for Nominatim — kept so main.py doesn't need changes) ──

async def get_http_client():
    return None   # not used


async def close_http_client() -> None:
    pass          # nothing to close


# ════════════════════════════════════════════════════════════
#  FORWARD GEOCODE  (address → lat/lng)
# ════════════════════════════════════════════════════════════

async def geocode(address: str) -> Optional[tuple[float, float]]:
    """
    Convert a human-readable address to (lat, lng).
    Enforces 1.1s gap between calls to respect OSM rate limit.
    Runs Nominatim's blocking call in a thread executor.
    """
    global _last_geocode_time
    import time

    # Throttle: wait if the last call was less than 1.1s ago
    elapsed = time.monotonic() - _last_geocode_time
    if elapsed < _RATE_DELAY:
        await asyncio.sleep(_RATE_DELAY - elapsed)

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _nom.geocode, address)
        _last_geocode_time = time.monotonic()
        if result:
            log.debug("Geocode OK", address=address, lat=result.latitude, lng=result.longitude)
            return (result.latitude, result.longitude)
        log.warning("Geocode no result", address=address)
    except Exception as e:
        log.error("Geocode error", address=address, error=str(e))

    return None


# ════════════════════════════════════════════════════════════
#  REVERSE GEOCODE  (lat/lng → city string)
# ════════════════════════════════════════════════════════════

async def reverse_geocode(lat: float, lng: float) -> str:
    """
    Convert coordinates to a human-readable "City, STATE" string.
    Falls back to raw coordinate string if lookup fails.
    """
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: _nom.reverse(f"{lat}, {lng}", exactly_one=True)
        )
        if result:
            addr  = result.raw.get("address", {})
            city  = (addr.get("city") or addr.get("town") or
                     addr.get("village") or addr.get("county") or "")
            state = addr.get("state_code") or addr.get("state") or ""
            if city:
                return f"{city}, {state}".strip(", ")
    except Exception as e:
        log.warning("Reverse geocode error", lat=lat, lng=lng, error=str(e))

    return f"{lat:.4f}, {lng:.4f}"


# ════════════════════════════════════════════════════════════
#  DISTANCE  (address → address, in miles)
# ════════════════════════════════════════════════════════════

async def distance_miles(
    loc1: str,
    loc2: str,
) -> tuple[float, tuple[float, float], tuple[float, float]]:
    """
    Returns (road_distance_miles, coords1, coords2).

    Nominatim requires sequential calls (1 req/sec policy) so
    loc1 and loc2 are geocoded one after the other, not concurrently.

    Road distance = geodesic × 1.25 (highway routing estimate).
    Falls back to Chicago → Dallas hardcoded pair on geocode failure.
    """
    ROAD_FACTOR = 1.25
    FALLBACK    = (920.0, (41.88, -87.63), (32.78, -96.80))

    c1 = await geocode(loc1)
    c2 = await geocode(loc2)   # sequential — respects 1 req/sec

    if not c1 or not c2:
        log.warning("distance_miles: geocode failed", loc1=loc1, loc2=loc2)
        return FALLBACK

    straight = geodesic(c1, c2).miles
    road     = round(straight * ROAD_FACTOR, 1)

    log.info("distance_miles", loc1=loc1, loc2=loc2, straight=round(straight, 1), road=road)
    return (road, c1, c2)