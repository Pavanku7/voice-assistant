"""
RemindersSkill — save, list, and check reminders.

Reminders persist in the shared :mod:`skills.userstore`. Each is stored as
``{"task": ..., "when_text": ..., "due_iso": ...|null, "created_iso": ...}``.

NOTE ON ALERTING: Meryna runs as a request/response assistant with no always-on
background timer, so it does not *pop up* an alert on its own when a reminder
comes due. Instead it tells you which reminders are due whenever you ask (or you
can ask "what are my reminders"). This keeps the feature reliable and honest
about what the platform can do today; a future background scheduler could add
active alerts without changing this skill's stored data.

Requirements addressed: 7.2, 7.5, 7.6
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, List, Optional

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill
from skills import userstore

logger = logging.getLogger("meryna.skills.reminders")

_NAMESPACE = "reminders"

_LEAD = re.compile(
    r"^(please\s+)?(set a reminder(?: to| for| about)?|remind me(?: to| about)?|"
    r"reminder(?: to| for| about)?)\s+",
    re.IGNORECASE,
)


class RemindersSkill(Skill):
    """Saves and reports reminders (no active pop-up alerts — see module note)."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "reminders-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        text = (context.utterance or "").strip()
        low = text.lower()

        if any(w in low for w in ("clear", "delete all", "remove all", "cancel all")):
            userstore.clear(_NAMESPACE)
            return SkillResponse(text="Cleared. You have no reminders now.")

        if "due" in low:
            return SkillResponse(text=self._render_due())

        if self._is_list_request(low):
            return SkillResponse(text=self._render_all())

        # Otherwise it's a new reminder.
        task, when_text, due_iso = self._parse(text)
        if not task:
            return SkillResponse(
                text="What should I remind you about?",
                follow_up_prompt="What's the reminder?",
            )
        userstore.add_item(
            _NAMESPACE,
            {
                "task": task,
                "when_text": when_text,
                "due_iso": due_iso,
                "created_iso": datetime.now().isoformat(timespec="seconds"),
            },
        )
        # Read naturally: "at 8 pm" / "tomorrow" already reads fine on its own,
        # so only add "for" when the phrase doesn't start with a preposition.
        if when_text and re.match(r"^(at|in|on|tomorrow|tonight|this)\b", when_text, re.IGNORECASE):
            when_phrase = f" {when_text}"
        elif when_text:
            when_phrase = f" for {when_text}"
        else:
            when_phrase = ""
        return SkillResponse(
            text=(
                f"Okay, I've saved a reminder to {task}{when_phrase}. "
                "Ask me any time and I'll tell you what's due."
            )
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self, text: str):
        """Return (task, when_text, due_iso) from the utterance."""
        body = _LEAD.sub("", text).strip().rstrip(".!")

        when_text = ""
        due_iso: Optional[str] = None

        # Find a trailing time phrase: "at 8 pm", "tomorrow", "at 3 pm tomorrow".
        m = re.search(
            r"\b(at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?(?:\s+tomorrow)?|tomorrow|"
            r"tonight|this evening|this afternoon|in the morning)\b",
            body,
            re.IGNORECASE,
        )
        if m:
            when_text = m.group(0).strip()
            due_iso = self._to_due_iso(when_text)
            # Strip the time phrase from the task text.
            body = (body[: m.start()] + body[m.end():]).strip()
            body = re.sub(r"\s{2,}", " ", body).strip(" ,")

        return body, when_text, due_iso

    @staticmethod
    def _to_due_iso(when_text: str) -> Optional[str]:
        """Best-effort convert a simple time phrase to an ISO datetime."""
        now = datetime.now()
        low = when_text.lower()
        target = now

        tm = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", low)
        if "tomorrow" in low:
            target = target + timedelta(days=1)

        if tm:
            hour = int(tm.group(1))
            minute = int(tm.group(2) or 0)
            meridiem = tm.group(3)
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            try:
                target = target.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
            except ValueError:
                return None
            # If a time-only phrase is already past today, assume tomorrow.
            if "tomorrow" not in low and target < now:
                target = target + timedelta(days=1)
            return target.isoformat(timespec="minutes")

        if "tonight" in low or "this evening" in low:
            return target.replace(hour=20, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
        if "this afternoon" in low:
            return target.replace(hour=15, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
        if "morning" in low:
            base = target + timedelta(days=1) if "tomorrow" in low else target
            return base.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
        if "tomorrow" in low:
            return target.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
        return None

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _is_list_request(low: str) -> bool:
        cues = ("what are my", "what's my", "list my", "my reminders", "show", "read")
        return any(c in low for c in cues)

    @staticmethod
    def _render_all() -> str:
        items = userstore.get_list(_NAMESPACE)
        if not items:
            return "You don't have any reminders saved."
        parts: List[str] = []
        for i, r in enumerate(items, start=1):
            task = r.get("task", "something")
            when = r.get("when_text")
            parts.append(f"{i}. {task}" + (f", {when}" if when else ""))
        return "Here are your reminders. " + ". ".join(parts) + "."

    @staticmethod
    def _render_due() -> str:
        items = userstore.get_list(_NAMESPACE)
        now = datetime.now()
        due = []
        for r in items:
            iso = r.get("due_iso")
            if not iso:
                continue
            try:
                if datetime.fromisoformat(iso) <= now:
                    due.append(r.get("task", "something"))
            except ValueError:
                continue
        if not due:
            return "Nothing is due right now."
        if len(due) == 1:
            return f"One reminder is due: {due[0]}."
        return "These reminders are due: " + ", ".join(due) + "."
