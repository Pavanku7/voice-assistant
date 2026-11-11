"""
MapsSkill — opens Google Maps in the default browser.

Builds a Google Maps search URL from the location/query in the utterance (or
extracted entities) and opens it with ``webbrowser.open`` (as in the legacy
``ToolKit.open_maps``).

Requirements addressed: 7.4, 7.5, 7.6
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import webbrowser
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.maps")

# Words we strip out to isolate the actual place/query.
_TRIGGER_WORDS = re.compile(
    r"\b(open|show|me|the|map|maps|navigate|to|directions?|where|is|find|"
    r"search|for|on|near|nearest|route|go|take|please|can|you)\b",
    re.IGNORECASE,
)


class MapsSkill(Skill):
    """Opens a Google Maps search for the requested location."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "maps-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        query = self._resolve_query(context)

        if query:
            url = (
                "https://www.google.com/maps/search/?api=1&query="
                + urllib.parse.quote(query)
            )
        else:
            url = "https://www.google.com/maps"

        try:
            opened = webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to open maps for %r: %s", query, exc)
            opened = False

        if not opened:
            return SkillResponse(
                text=(
                    "I couldn't open the maps in your browser just now, "
                    "but you can search for "
                    f"{query or 'the location'} on Google Maps."
                )
            )

        if query:
            return SkillResponse(
                text=f"I've opened Google Maps with a search for {query}."
            )
        return SkillResponse(text="I've opened Google Maps for you.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_query(self, context: SkillContext) -> str:
        """Determine the maps search query from entities or the utterance."""
        entities = context.entities or {}
        for key in ("location", "place", "destination", "query"):
            value = entities.get(key)
            if value:
                return str(value).strip()

        # Fall back to stripping trigger words from the raw utterance.
        stripped = _TRIGGER_WORDS.sub(" ", context.utterance or "")
        stripped = re.sub(r"\s+", " ", stripped).strip(" ?.!,")
        return stripped
