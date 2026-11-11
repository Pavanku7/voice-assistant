"""
WikipediaSkill — short encyclopedia summaries (no API key).

Uses Wikipedia's free REST summary endpoint
(``en.wikipedia.org/api/rest_v1/page/summary/<title>``). Resolves the topic
from the utterance, fetches the summary, and returns the first couple of
sentences trimmed to a spoken-friendly length. Falls back to a plain web search
(and, if available, the AI) when there's no direct page.

Requirements addressed: 7.2, 7.5, 7.6, 7.8
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Optional

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill
from skills import websearch

logger = logging.getLogger("meryna.skills.wikipedia")

_SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_SEARCH_API = "https://en.wikipedia.org/w/api.php"
_TIMEOUT = 8
_MAX_SENTENCES = 3

_LEAD = re.compile(
    r"^(please\s+)?(tell me about|give me (?:a )?(?:summary|overview|info(?:rmation)?)"
    r"(?: of| about| on)?|who (?:is|was|are|were)|what (?:is|was|are|were)(?: the)?|"
    r"info(?:rmation)? (?:about|on)|summary of)\s+",
    re.IGNORECASE,
)


class WikipediaSkill(Skill):
    """Fetches concise Wikipedia summaries."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "wikipedia-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        topic = self._extract_topic(context)
        if not topic:
            return SkillResponse(
                text="What would you like me to tell you about?",
                follow_up_prompt="Which topic?",
            )

        try:
            summary = await asyncio.to_thread(self._fetch_summary, topic)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Wikipedia fetch failed for %r: %s", topic, exc)
            summary = None

        if summary:
            return SkillResponse(text=summary)

        # No direct page — fall back to a web search summary.
        try:
            found = await asyncio.to_thread(websearch.search, topic, 3)
            if not found.is_empty:
                text = found.answer or (found.results[0].snippet if found.results else "")
                if text:
                    return SkillResponse(text=self._trim(text))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Wikipedia web fallback failed: %s", exc)

        return SkillResponse(
            text=f"I couldn't find a summary about {topic}. "
            "Could you try naming it differently?"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_topic(self, context: SkillContext) -> str:
        entities = context.entities or {}
        for key in ("topic", "subject", "query", "entity"):
            val = entities.get(key)
            if val:
                return str(val).strip()
        text = (context.utterance or "").strip().rstrip("?.!")
        stripped = _LEAD.sub("", text).strip()
        return stripped or text

    def _fetch_summary(self, topic: str) -> Optional[str]:
        # 1. Try a direct summary by title.
        direct = self._summary_for_title(topic)
        if direct:
            return direct
        # 2. Search for the closest page title, then summarise it.
        title = self._search_title(topic)
        if title and title.lower() != topic.lower():
            return self._summary_for_title(title)
        return None

    def _summary_for_title(self, title: str) -> Optional[str]:
        url = _SUMMARY_API + urllib.parse.quote(title.replace(" ", "_"))
        req = urllib.request.Request(url, headers={"User-Agent": "Meryna/1.0 (voice assistant)"})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            return None
        if data.get("type") == "disambiguation":
            return None
        extract = (data.get("extract") or "").strip()
        return self._trim(extract) if extract else None

    def _search_title(self, topic: str) -> Optional[str]:
        params = urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": topic,
             "format": "json", "srlimit": 1}
        )
        req = urllib.request.Request(
            f"{_SEARCH_API}?{params}",
            headers={"User-Agent": "Meryna/1.0 (voice assistant)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            return None
        hits = (data.get("query") or {}).get("search") or []
        return hits[0].get("title") if hits else None

    @staticmethod
    def _trim(text: str) -> str:
        """Keep the first few sentences so the reply stays TTS-friendly."""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        return " ".join(sentences[:_MAX_SENTENCES]).strip()
