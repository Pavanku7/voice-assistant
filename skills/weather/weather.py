"""
WeatherSkill — current conditions and a short forecast via wttr.in.

Extracts a location entity (falling back to a default), fetches current
temperature / humidity / conditions plus a brief forecast from the free
``wttr.in`` JSON API, and returns a spoken-friendly summary.  If the service
is unavailable, returns a graceful "temporarily unavailable" message
(Requirement 7.7).

Requirements addressed: 7.1, 7.5, 7.6, 7.7
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
import urllib.request
import json
from typing import Any, Optional

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill
from skills.geolocation import detect_location

logger = logging.getLogger("meryna.skills.weather")

# Used only as a last resort if the location can be neither named by the user
# nor auto-detected from the network.
_DEFAULT_LOCATION = "Bengaluru"
_REQUEST_TIMEOUT = 5  # seconds


class WeatherSkill(Skill):
    """Fetches weather conditions and forecast from wttr.in."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "weather-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        # query = what we send to wttr.in (may be "lat,lon"); display = what we
        # say back to the user (always a human-readable place name).
        query, display = await self._resolve_location(context)

        try:
            summary = await asyncio.to_thread(
                self._fetch_weather, query, display
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weather lookup failed for %r: %s", query, exc)
            return SkillResponse(
                text=(
                    "The weather service is temporarily unavailable. "
                    "Please try again in a little while."
                )
            )

        if summary is None:
            return SkillResponse(
                text=(
                    "The weather service is temporarily unavailable. "
                    "Please try again in a little while."
                )
            )

        return SkillResponse(text=summary)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_location(self, context: SkillContext) -> tuple[str, str]:
        """Return a ``(query, display)`` pair for the weather lookup.

        Precedence: a place named in the utterance/entities → a saved user
        preference → the current location auto-detected from the network →
        the built-in default.  ``query`` is what we send to wttr.in (possibly
        ``"lat,lon"`` coordinates) and ``display`` is the friendly name we say
        back to the user.
        """
        entities = context.entities or {}
        for key in ("location", "city", "place"):
            value = entities.get(key)
            if value:
                name = str(value).strip()
                return name, name

        prefs = context.user_preferences or {}
        if prefs.get("location"):
            name = str(prefs["location"]).strip()
            return name, name

        # No place given — auto-detect from the network (no setup required).
        detected = await asyncio.to_thread(detect_location)
        if detected and detected.query:
            return detected.query, detected.place_name

        return _DEFAULT_LOCATION, _DEFAULT_LOCATION

    @staticmethod
    def _fetch_weather(location: str, display: Optional[str] = None) -> Optional[str]:
        """Fetch and format weather for *location* from wttr.in (blocking).

        *location* is the wttr.in query (a place name or ``"lat,lon"``);
        *display* is the human-readable name spoken back to the user.
        """
        say_name = display or location
        quoted = urllib.parse.quote(location)
        url = f"https://wttr.in/{quoted}?format=j1"

        req = urllib.request.Request(url, headers={"User-Agent": "Meryna/1.0"})
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))

        current = (data.get("current_condition") or [{}])[0]
        temp_c = current.get("temp_C", "?")
        feels_c = current.get("FeelsLikeC", temp_c)
        humidity = current.get("humidity", "?")
        desc_list = current.get("weatherDesc") or [{}]
        conditions = desc_list[0].get("value", "unclear conditions").strip()

        # Forecast: today's max/min if present.
        forecast_txt = ""
        weather_days = data.get("weather") or []
        if weather_days:
            today = weather_days[0]
            max_c = today.get("maxtempC")
            min_c = today.get("mintempC")
            if max_c and min_c:
                forecast_txt = (
                    f" Today's range is between {min_c} and {max_c} degrees."
                )

        return (
            f"Right now in {say_name} it's {temp_c} degrees Celsius with "
            f"{conditions.lower()}, feels like {feels_c} degrees, and humidity "
            f"is around {humidity} percent.{forecast_txt}"
        )
