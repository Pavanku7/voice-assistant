"""
HomeworkHelperSkill — safe, age-appropriate homework help for ages 6-15.

Answers school questions in simple language. For factual questions it first
searches the web (via the shared, key-free :mod:`skills.websearch` helper) so
answers stay current, then has the AI explain the result at a child-friendly
level. A child-safety instruction keeps content appropriate and steers away
from anything unsafe.

Requirements addressed: 7.2, 7.5, 7.6, 7.8
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill
from skills import websearch

logger = logging.getLogger("meryna.skills.homework_helper")

# Prepended to every homework answer — keeps replies age-appropriate and safe.
_SAFETY_AND_STYLE = (
    "You are Meryna, a kind and patient tutor helping a school student who may "
    "be a child between 6 and 15 years old. Explain in simple, encouraging, "
    "age-appropriate language, using short sentences and a friendly tone. Give "
    "one small everyday example when it helps. Keep the whole answer short "
    "enough to be read aloud (a few sentences). Reply in the same language the "
    "student used (English, Hindi, or Nepali). "
    "SAFETY: keep everything suitable for children. Never include violent, "
    "sexual, hateful, self-harm, or otherwise adult or unsafe content. If the "
    "question is inappropriate for a child or asks for something harmful, gently "
    "decline and suggest asking a parent, teacher, or trusted adult. Do not just "
    "give a final answer to plug into a worksheet — briefly explain the thinking "
    "so the student actually learns."
)

# When true, the utterance is asking for a current/factual thing worth a web
# lookup; pure "explain a concept" questions the AI can handle from knowledge.
_LOOKUP_HINTS = (
    "who", "when", "where", "how many", "how much", "how tall", "how far",
    "capital", "population", "year", "date", "largest", "longest", "highest",
    "tallest", "fastest", "distance", "born", "died", "invented", "discovered",
    "what is the", "who is", "who was", "look up", "search",
)


class HomeworkHelperSkill(Skill):
    """Explains schoolwork simply and safely, searching the web when useful."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "homework-helper-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        question = (context.utterance or "").strip()
        if not question:
            return SkillResponse(
                text="Sure! What would you like help with?",
                follow_up_prompt="What's the homework question?",
            )

        if self._ai_provider is None:
            return SkillResponse(
                text=(
                    "My learning engine isn't available right now, so I can't "
                    "help with homework this moment. Please try again soon."
                )
            )

        # For factual questions, gather web context first.
        web_context = ""
        if self._should_search(question):
            try:
                found = await asyncio.to_thread(websearch.search, question, 4)
                if not found.is_empty:
                    web_context = found.as_text(max_results=3)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Homework web lookup failed: %s", exc)

        prompt = self._build_prompt(question, web_context)
        try:
            reply = await self._ai_provider.generate_text(
                prompt=prompt,
                conversation_history=context.conversation_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Homework AI generation failed: %s", exc)
            return SkillResponse(
                text=(
                    "I had trouble working that out just now. "
                    "Could you ask me again?"
                )
            )

        reply = (reply or "").strip()
        if not reply:
            reply = "Let's take it step by step — can you tell me a bit more?"
        return SkillResponse(text=reply)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _should_search(question: str) -> bool:
        q = question.lower()
        return any(hint in q for hint in _LOOKUP_HINTS)

    @staticmethod
    def _build_prompt(question: str, web_context: str) -> str:
        parts = [_SAFETY_AND_STYLE, "", f"Student's question: {question}"]
        if web_context:
            parts += [
                "",
                "Here are some facts from the web to help you answer "
                "accurately (use them, but explain in your own simple words):",
                web_context,
            ]
        return "\n".join(parts)
