"""
Geolocation helper — approximate the user's location from their public IP.

Provides a single :func:`detect_location` function shared by the weather and
location skills so that "where am I" / "weather now" work without the user
configuring anything.  This is *IP-based*, city-level geolocation: it needs no
API key, no browser permission, and no Google account — it simply asks a free
public service which city the current internet connection appears to be in.

Because it is IP-based, accuracy is city-level (and can be off if a VPN is in
use).  It is a plain module, not a skill package, so the Skill Registry (which
only loads sub-directories containing a ``manifest.json``) never treats it as a
skill.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("meryna.skills.geolocation")

_REQUEST_TIMEOUT = 5  # seconds
_USER_AGENT = "Meryna/1.0"


@dataclass
class DetectedLocation:
    """A best-effort, IP-derived location."""

    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def place_name(self) -> str:
        """A short, speakable place name (city first, else region/country)."""
        parts: List[str] = [p for p in (self.city, self.region, self.country) if p]
        # Avoid saying e.g. "Bengaluru, Karnataka, India" — keep it to the two
        # most specific, non-duplicate parts.
        seen: List[str] = []
        for p in parts:
            if p not in seen:
                seen.append(p)
        return ", ".join(seen[:2]) if seen else "an unknown location"

    @property
    def query(self) -> str:
        """A location string suitable for a weather lookup."""
        if self.latitude is not None and self.longitude is not None:
            return f"{self.latitude},{self.longitude}"
        return self.city or self.region or self.country or ""


def detect_location() -> Optional[DetectedLocation]:
    """Return the caller's approximate location, or ``None`` if undetectable.

    Tries providers in order of accuracy:

    1. **Windows location service** (WiFi/GPS based, via ``winrt``) — accurate
       to the actual physical location, not the ISP's exit point.  Requires
       Windows location to be enabled and permission granted; skipped silently
       elsewhere.
    2. **ipinfo.io** then **ip-api.com** — free, key-less IP geolocation.
       Accurate only to the ISP's network hub (e.g. an ISP that routes Sikkim
       traffic through Delhi will report Delhi).

    Blocking — call it from a worker thread (e.g. ``asyncio.to_thread``).
    """
    for provider in (_detect_via_windows, _detect_via_ipinfo, _detect_via_ip_api):
        try:
            result = provider()
        except Exception as exc:  # noqa: BLE001 — try the next provider.
            logger.debug("Geolocation provider %s failed: %s", provider.__name__, exc)
            continue
        if result and (result.city or result.latitude is not None):
            logger.debug("Geolocation resolved to %s", result.place_name)
            return result
    logger.info("Geolocation could not determine the current location.")
    return None


# ----------------------------------------------------------------------
# Providers
# ----------------------------------------------------------------------

def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        if resp.status != 200:
            raise OSError(f"HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def _detect_via_windows() -> Optional[DetectedLocation]:
    """Use the Windows location service (WiFi/GPS) — Windows only.

    Reads precise coordinates from the OS, then reverse-geocodes them to a
    city name so the place can be spoken.  Returns ``None`` on any platform
    without ``winrt`` or when location access is denied/disabled.
    """
    import sys

    if not sys.platform.startswith("win"):
        return None

    try:
        import asyncio

        from winrt.windows.devices.geolocation import Geolocator, PositionAccuracy
    except Exception:  # noqa: BLE001 — winrt not installed / unavailable.
        return None

    async def _read() -> Optional[tuple[float, float]]:
        access = await Geolocator.request_access_async()
        # 1 == GeolocationAccessStatus.ALLOWED
        if int(access) != 1:
            return None
        locator = Geolocator()
        locator.desired_accuracy = PositionAccuracy.HIGH
        pos = await locator.get_geoposition_async()
        point = pos.coordinate.point.position
        return float(point.latitude), float(point.longitude)

    # winrt coroutines need their own event loop when called from a worker
    # thread (asyncio.to_thread), since that thread has no running loop.
    coords = asyncio.new_event_loop().run_until_complete(_read())
    if coords is None:
        return None

    lat, lon = coords
    loc = _reverse_geocode(lat, lon)
    if loc is None:
        loc = DetectedLocation(latitude=lat, longitude=lon)
    else:
        loc.latitude, loc.longitude = lat, lon
    return loc


def _reverse_geocode(lat: float, lon: float) -> Optional[DetectedLocation]:
    """Turn coordinates into a city/region/country name (free, key-less)."""
    url = (
        "https://api.bigdatacloud.net/data/reverse-geocode-client"
        f"?latitude={lat}&longitude={lon}&localityLanguage=en"
    )
    try:
        data = _get_json(url)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Reverse geocode failed: %s", exc)
        return None
    city = data.get("city") or data.get("locality") or None
    region = data.get("principalSubdivision") or None
    country = data.get("countryName") or None
    return DetectedLocation(city=city, region=region, country=country)


def _detect_via_ipinfo() -> Optional[DetectedLocation]:
    """Query https://ipinfo.io/json (HTTPS, no key for modest usage)."""
    data = _get_json("https://ipinfo.io/json")
    lat = lon = None
    loc = data.get("loc")  # "lat,lon"
    if loc and "," in loc:
        try:
            lat_s, lon_s = loc.split(",", 1)
            lat, lon = float(lat_s), float(lon_s)
        except (TypeError, ValueError):
            lat = lon = None
    return DetectedLocation(
        city=data.get("city") or None,
        region=data.get("region") or None,
        country=data.get("country") or None,
        latitude=lat,
        longitude=lon,
    )


def _detect_via_ip_api() -> Optional[DetectedLocation]:
    """Query http://ip-api.com/json (HTTP-only on the free tier)."""
    data = _get_json("http://ip-api.com/json/")
    if str(data.get("status", "")).lower() == "fail":
        return None
    return DetectedLocation(
        city=data.get("city") or None,
        region=data.get("regionName") or None,
        country=data.get("country") or None,
        latitude=data.get("lat"),
        longitude=data.get("lon"),
    )
