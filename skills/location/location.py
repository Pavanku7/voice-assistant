"""
LocationSkill — answers "where am I" using automatic IP-based geolocation.

When the user asks for their current location, this skill auto-detects the
approximate place from the network connection (no Google account, no browser
permission, no manual setup) and reports it — optionally followed by the
current weather there, since "where am I / what's it like" tend to go together.

Requirements addressed: 7.5, 7.6, 7.7
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill
from skills.geolocation import DetectedLocation, detect_location

logger = logging.getLogger("meryna.skills.location")


class LocationSkill(Skill):
    """Reports the user's current (approximate) location and local weather."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "location-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        # 1. A location the user has saved as a preference always wins — it's
        #    the most reliable signal (they told us directly).
        prefs = context.user_preferences or {}
        saved = str(prefs.get("location") or "").strip()
        if saved:
            detected = DetectedLocation(city=saved)
            weather = await self._maybe_weather(detected)
            place = saved
            if weather:
                return SkillResponse(
                    text=f"You're in {place}. {weather}"
                )
            return SkillResponse(text=f"You're in {place}.")

        # 2. No saved location — auto-detect (Windows location, then IP).
        detected = await asyncio.to_thread(detect_location)

        if detected is None or not detected.place_name or detected.place_name == "an unknown location":
            return SkillResponse(
                text=(
                    "I wasn't able to pin down your location just now. "
                    "This usually needs Windows location or an internet "
                    "connection, and a VPN can throw it off. If you tell me the "
                    "city, I'll remember it."
                )
            )

        place = detected.place_name
        weather = await self._maybe_weather(detected)

        if weather:
            text = f"You appear to be in {place}. {weather}"
        else:
            text = (
                f"You appear to be in {place}. "
                "Do note this is an approximate, auto-detected location."
            )

        return SkillResponse(text=text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _maybe_weather(self, detected: DetectedLocation) -> Optional[str]:
        """Fetch current weather for the detected location, best-effort."""
        query = detected.query
        if not query:
            return None
        try:
            # Reuse the weather skill's fetcher for a consistent summary.
            from skills.weather.weather import WeatherSkill

            return await asyncio.to_thread(
                WeatherSkill._fetch_weather, query, detected.place_name
            )
        except Exception as exc:  # noqa: BLE001 — weather is a nice-to-have here.
            logger.debug("Location weather lookup failed: %s", exc)
            return None
