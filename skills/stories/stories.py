"""
StoriesSkill — short, gentle, child-safe stories (AI-generated).

Asks the AI provider for a short story with a strong safety instruction so
content stays appropriate for children. Honours a topic mentioned in the
request ("a story about the moon"). Replies in the user's language.

Requirements addressed: 7.2, 7.5, 7.6
"""

from __future__ import annotations

import logging
import re
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.stories")

_SAFETY = (
    "You are a warm storyteller for children. Tell ONE short, original, gentle "
    "story of about 6 to 10 sentences. Keep it wholesome and age-appropriate: "
    "no violence, fear, sadness that lingers, or any adult, scary, or unsafe "
    "content. Give it a kind message and a happy ending. Write it to be read "
    "aloud, with simple words and no markdown. Reply in the same language the "
    "user used (English, Hindi, or Nepali)."
)

_TOPIC = re.compile(r"\b(?:about|on|of)\s+(.+)$", re.IGNORECASE)


class StoriesSkill(Skill):
    """Tells short, child-friendly stories."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "stories-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        if self._ai_provider is None:
            return SkillResponse(
                text=(
                    "I need my storytelling engine for this, and it's not "
                    "available right now. Please try again soon."
                )
            )

        topic = self._topic(context.utterance or "")
        instruction = _SAFETY
        if topic:
            instruction += f"\n\nMake the story about: {topic}."
        else:
            instruction += "\n\nChoose a delightful topic yourself."

        try:
            story = await self._ai_provider.generate_text(
                prompt=instruction,
                conversation_history=context.conversation_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Story generation failed: %s", exc)
            return SkillResponse(
                text="I couldn't think of a story just now. Ask me again in a bit?"
            )

        story = (story or "").strip()
        if not story:
            story = (
                "Once upon a time, a little star was afraid to shine. A kind moon "
                "whispered, 'Just be yourself.' The star glowed softly, and soon "
                "the whole sky smiled. The end."
            )
        return SkillResponse(text=story)

    @staticmethod
    def _topic(text: str) -> str:
        m = _TOPIC.search(text.strip().rstrip(".!?"))
        if m:
            topic = m.group(1).strip()
            # Drop trailing "for my kid" style bits.
            topic = re.sub(r"\bfor (my|the) \w+.*$", "", topic, flags=re.IGNORECASE).strip()
            return topic
        return ""
