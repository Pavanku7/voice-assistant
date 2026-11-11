"""
TranslatorSkill — translate between languages (AI-powered).

Focused on English, Hindi, and Nepali (Meryna's supported languages) but the
AI can handle others too. The reply includes the translated text, so Meryna's
language-aware TTS automatically speaks it in the matching voice (e.g. a Hindi
translation is read in the Hindi voice).

Requirements addressed: 7.2, 7.5, 7.6
"""

from __future__ import annotations

import logging
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.translator")


class TranslatorSkill(Skill):
    """Translates words and phrases between languages."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "translator-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        request = (context.utterance or "").strip()
        if not request:
            return SkillResponse(
                text="What would you like me to translate?",
                follow_up_prompt="What should I translate, and into which language?",
            )

        if self._ai_provider is None:
            return SkillResponse(
                text=(
                    "My translation engine isn't available right now. "
                    "Please try again soon."
                )
            )

        prompt = (
            "You are a translator. The user's request is below. Work out what "
            "they want translated and into which language, then give the "
            "translation. Support English, Hindi, and Nepali especially. "
            "Answer in this spoken-friendly form: say the translation, then, if "
            "the target is not English, add a simple pronunciation in brackets "
            "and a very short note on usage if helpful. Keep it brief. If the "
            "target language is unclear, assume they want it in the other of "
            "English/Hindi/Nepali.\n\n"
            f"Request: {request}"
        )
        try:
            reply = await self._ai_provider.generate_text(
                prompt=prompt,
                conversation_history=context.conversation_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Translation failed: %s", exc)
            return SkillResponse(
                text="I had trouble translating that. Could you say it again?"
            )

        reply = (reply or "").strip()
        if not reply:
            reply = "I couldn't translate that. Could you rephrase it?"
        return SkillResponse(text=reply)
