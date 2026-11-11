"""
SupportSkill — calm, caring responses for someone in distress.

Meryna is not a therapist and this skill never pretends to be one. Its job is
to respond with warmth, encourage the person to reach out to someone they
trust, and — crucially — surface real helpline information when the message
suggests a crisis or possible self-harm. Safety takes priority over everything
else, so the crisis pathway does NOT depend on the AI or the network: if a
crisis phrase is detected, a fixed, reviewed message with helpline numbers is
returned directly.

For general (non-crisis) distress, it uses the AI for a gentle, personalised
reply when available, always appended with a gentle nudge to talk to a trusted
adult or friend.

Helpline numbers below are India-focused (Meryna's primary user base) plus an
international pointer. Update these for your region.

Requirements addressed: 7.2, 7.5, 7.6, 7.8
"""

from __future__ import annotations

import logging
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.support")

# Phrases that indicate a possible crisis / self-harm — trigger the fixed,
# network-independent safety response. Kept broad and lowercase.
_CRISIS_PHRASES = (
    "kill myself", "killing myself", "end my life", "ending my life",
    "want to die", "wanna die", "don't want to be here", "dont want to be here",
    "don't want to live", "dont want to live", "no reason to live",
    "hurt myself", "harm myself", "self harm", "self-harm", "cut myself",
    "suicide", "suicidal", "better off dead", "take my own life",
)

# Reviewed, fixed crisis message. Not AI-generated on purpose.
_CRISIS_MESSAGE = (
    "I'm really sorry you're feeling this way, and I'm glad you told me. "
    "You matter, and you don't have to go through this alone. "
    "Please reach out right now to someone who can help: in India you can call "
    "the KIRAN mental health helpline at 1800-599-0019, any time, day or night. "
    "You can also call Tele-MANAS at 14416. "
    "If you are in immediate danger, please call your local emergency number. "
    "And if there's a parent, teacher, or friend nearby, please tell them how "
    "you're feeling. I'm here with you."
)

# Gentle closing nudge appended to general-distress replies.
_GENTLE_NUDGE = (
    " If it helps, talking to someone you trust — a parent, a teacher, or a "
    "good friend — can make things feel lighter. I'm here whenever you want to "
    "talk."
)

_SUPPORT_PROMPT = (
    "The user is feeling upset or low. Reply with genuine warmth and empathy in "
    "two or three short sentences. Validate their feelings, be gentle and "
    "encouraging, and do not give clinical or medical advice. Do not be "
    "dismissive or overly cheerful. Reply in the user's language. Keep it "
    "TTS-friendly with no markdown."
)


class SupportSkill(Skill):
    """Offers calm emotional support and crisis helpline information."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "support-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        text = (context.utterance or "").lower()

        # 1. Crisis pathway — fixed, immediate, never depends on AI/network.
        if any(phrase in text for phrase in _CRISIS_PHRASES):
            logger.info("Support skill: crisis pathway triggered.")
            return SkillResponse(text=_CRISIS_MESSAGE)

        # 2. General distress — warm AI reply plus a gentle nudge.
        if self._ai_provider is not None:
            try:
                reply = await self._ai_provider.generate_text(
                    prompt=f"{_SUPPORT_PROMPT}\n\nThey said: {context.utterance}",
                    conversation_history=context.conversation_history,
                )
                reply = (reply or "").strip()
                if reply:
                    return SkillResponse(text=reply + _GENTLE_NUDGE)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Support AI reply failed: %s", exc)

        # 3. Fallback if AI unavailable.
        return SkillResponse(
            text=(
                "I'm sorry you're feeling this way. Your feelings are valid, and "
                "you're not alone." + _GENTLE_NUDGE
            )
        )
