"""
WebSearchSkill — answers factual questions by searching the web (no API key).

Uses the shared, key-free :mod:`skills.websearch` helper (DuckDuckGo) to fetch
facts and snippets, then asks the AI provider to turn them into one short,
spoken-friendly answer in the user's language. If the AI is unavailable it
reads back the top snippet directly, so the skill still works degraded.

Requirements addressed: 7.2, 7.5, 7.6, 7.8
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill
from skills import websearch

logger = logging.getLogger("meryna.skills.web_search")


class WebSearchSkill(Skill):
    """Looks things up on the web and answers in plain language."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "web-search-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        query = self._query(context)
        if not query:
            return SkillResponse(
                text="What would you like me to look up?",
                follow_up_prompt="What should I search for?",
            )

        try:
            found = await asyncio.to_thread(websearch.search, query, 5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Web search failed: %s", exc)
            return SkillResponse(
                text=(
                    "I couldn't reach the web just now. "
                    "Please try again in a moment."
                )
            )

        if found.is_empty:
            return SkillResponse(
                text=(
                    f"I couldn't find anything useful about {query}. "
                    "Try rephrasing it?"
                )
            )

        answer = await self._summarise(query, found, context)
        return SkillResponse(text=answer)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _query(context: SkillContext) -> str:
        """Best search query: an extracted entity, else the raw utterance."""
        entities = context.entities or {}
        for key in ("query", "search_query", "topic", "subject"):
            val = entities.get(key)
            if val:
                return str(val).strip()
        return (context.utterance or "").strip()

    async def _summarise(
        self, query: str, found: websearch.SearchResponse, context: SkillContext
    ) -> str:
        """Turn raw search text into one concise spoken answer via the AI."""
        source_text = found.as_text(max_results=3)

        if self._ai_provider is None:
            # No AI — read back the most direct thing we found.
            return found.answer or (
                found.results[0].snippet or found.results[0].title
                if found.results
                else "I found some results but can't summarise them right now."
            )

        prompt = (
            "Answer the user's question in one or two short, natural sentences "
            "suitable for reading aloud. Use ONLY the web search results below. "
            "If they don't contain the answer, say you couldn't find it. Do not "
            "mention that you searched or cite sources.\n\n"
            f"User question: {query}\n\n"
            f"Web search results:\n{source_text}"
        )
        try:
            reply = await self._ai_provider.generate_text(
                prompt=prompt,
                conversation_history=context.conversation_history,
            )
            reply = (reply or "").strip()
            if reply:
                return reply
        except Exception as exc:  # noqa: BLE001
            logger.debug("AI summarise failed, using raw snippet: %s", exc)

        return found.answer or (found.results[0].snippet if found.results else "")
