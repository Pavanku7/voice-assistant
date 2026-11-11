"""
DateTimeSkill — current time, date, and day of the week (offline).

Reads the local system clock, so it works with no network and no API key.
Chooses what to report based on what the user asked (time vs. date vs. day),
and defaults to a friendly "it's <time> on <date>" when unsure.

Requirements addressed: 7.2, 7.5, 7.6
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.datetime")


class DateTimeSkill(Skill):
    """Reports the local time and date."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "datetime-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        now = datetime.now()
        text = (context.utterance or "").lower()

        wants_time = any(w in text for w in ("time", "clock", "morning", "evening", "afternoon", "o'clock"))
        wants_date = any(w in text for w in ("date", "today", "month", "year", "day"))

        clock = now.strftime("%I:%M %p").lstrip("0")
        date_str = now.strftime("%A, %d %B %Y")
        day_name = now.strftime("%A")

        if wants_time and not wants_date:
            reply = f"It's {clock}."
        elif wants_date and not wants_time:
            if "day" in text and "date" not in text and "today" not in text:
                reply = f"Today is {day_name}."
            else:
                reply = f"Today is {date_str}."
        else:
            reply = f"It's {clock} on {date_str}."

        return SkillResponse(text=reply)
