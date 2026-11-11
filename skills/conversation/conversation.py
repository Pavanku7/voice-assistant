"""
ConversationSkill — the default fallback skill.

Passes the user's utterance and recent conversation history to the
``AIProviderManager`` and returns the generated reply.  This is the skill the
Intent Router falls back to when nothing else matches (Requirement 2.3).

Requirements addressed: 7.3, 7.5, 7.6
"""

from __future__ import annotations

import logging
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.conversation")


class ConversationSkill(Skill):
    """Handles general chat by delegating to the AI provider."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "conversation-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        """Generate a conversational reply from the AI provider."""
        if self._ai_provider is None:
            return SkillResponse(
                text=(
                    "My language engine isn't available right now, so I can't "
                    "chat. Please check the AI service settings."
                )
            )

        reply = await self._ai_provider.generate_text(
            prompt=context.utterance,
            conversation_history=context.conversation_history,
        )

        reply = (reply or "").strip()
        if not reply:
            reply = "I'm not sure how to respond to that. Could you rephrase it?"

        return SkillResponse(text=reply)
