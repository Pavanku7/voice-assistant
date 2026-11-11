"""
NotesSkill — a persistent personal notes / to-do list.

Add items, read them back, or clear the list. Items persist between sessions
in the shared :mod:`skills.userstore` (``~/.meryna_userdata.json``). No network
or AI needed — it's fully local and always available.

Requirements addressed: 7.2, 7.5, 7.6
"""

from __future__ import annotations

import logging
import re
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill
from skills import userstore

logger = logging.getLogger("meryna.skills.notes")

_NAMESPACE = "notes"

# Phrases stripped from the front of an "add" request to isolate the item.
_ADD_LEAD = re.compile(
    r"^(please\s+)?(add|make a note(?: to)?|note(?: down)?|remind me to|"
    r"put|write down|save)\s+",
    re.IGNORECASE,
)
_ADD_TAIL = re.compile(r"\s+(to|on|in)\s+my\s+(to-?do|todo|notes?|list).*$", re.IGNORECASE)


class NotesSkill(Skill):
    """Manages a saved notes / to-do list."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "notes-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        text = (context.utterance or "").strip()
        low = text.lower()

        # Clear.
        if any(w in low for w in ("clear", "delete all", "empty", "remove everything")):
            userstore.clear(_NAMESPACE)
            return SkillResponse(text="Done. Your to-do list is now empty.")

        # Read back.
        if self._is_read_request(low):
            return SkillResponse(text=self._render_list())

        # Otherwise treat as an add.
        item = self._extract_item(text)
        if not item:
            return SkillResponse(
                text="What would you like me to add to your list?",
                follow_up_prompt="What should I add?",
            )
        items = userstore.add_item(_NAMESPACE, item)
        return SkillResponse(
            text=f"Added '{item}' to your list. You now have {len(items)} "
            f"item{'s' if len(items) != 1 else ''}."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_read_request(low: str) -> bool:
        read_cues = (
            "what's on", "whats on", "what is on", "read", "show", "list",
            "what do i have", "tell me my", "my notes", "my to-do", "my todo",
        )
        # An "add" verb overrides a read cue ("add X to my list" is an add).
        if _ADD_LEAD.search(low):
            return False
        return any(cue in low for cue in read_cues)

    def _extract_item(self, text: str) -> str:
        item = _ADD_LEAD.sub("", text).strip()
        item = _ADD_TAIL.sub("", item).strip()
        return item.rstrip(".!").strip()

    @staticmethod
    def _render_list() -> str:
        items = userstore.get_list(_NAMESPACE)
        if not items:
            return "Your to-do list is empty right now."
        lines = ", ".join(f"{i}. {it}" for i, it in enumerate(items, start=1))
        return f"Here's your list. {lines}."
