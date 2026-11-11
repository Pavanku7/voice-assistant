"""
NewsSkill — top recent headlines via Google News RSS.

Fetches up to five recent headlines using ``feedparser`` (as in the legacy
``ToolKit.get_news``) and returns a short, spoken-friendly summary.  If the
feed is unavailable, returns a graceful "temporarily unavailable" message
(Requirement 7.8).

Requirements addressed: 7.2, 7.5, 7.6, 7.8
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.news")

_NEWS_FEED = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
_MAX_HEADLINES = 5


class NewsSkill(Skill):
    """Reads out top recent news headlines."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "news-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        try:
            headlines = await asyncio.to_thread(self._fetch_headlines)
        except Exception as exc:  # noqa: BLE001
            logger.warning("News lookup failed: %s", exc)
            return SkillResponse(
                text=(
                    "The news service is temporarily unavailable. "
                    "Please try again in a little while."
                )
            )

        if not headlines:
            return SkillResponse(
                text=(
                    "The news service is temporarily unavailable. "
                    "Please try again in a little while."
                )
            )

        intro = "Here are the top headlines right now. "
        body = " ".join(
            f"{i}. {title}." for i, title in enumerate(headlines, start=1)
        )
        return SkillResponse(text=intro + body)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_headlines() -> Optional[List[str]]:
        """Fetch up to five recent headlines from Google News RSS (blocking)."""
        import feedparser

        feed = feedparser.parse(_NEWS_FEED)
        entries = getattr(feed, "entries", None)
        if not entries:
            return None

        headlines: List[str] = []
        for entry in entries[:_MAX_HEADLINES]:
            title = getattr(entry, "title", "").strip()
            if title:
                headlines.append(title)
        return headlines or None
