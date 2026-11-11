"""
FunSkill — clean jokes and fun facts.

Jokes come from the free, key-free JokeAPI with the ``safe-mode`` and blacklist
flags set so results stay family-friendly (important for child users). Fun
facts come from the free ``uselessfacts`` API. If a service is down, the skill
asks the AI for a clean joke/fact, and if that's unavailable too it falls back
to a small built-in list — so it always has something to say.

Requirements addressed: 7.2, 7.5, 7.6, 7.8
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import Any, Optional

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.fun")

# safe-mode + blacklisted categories keep jokes appropriate for children.
_JOKE_API = (
    "https://v2.jokeapi.dev/joke/Any"
    "?safe-mode&blacklistFlags=nsfw,religious,political,racist,sexist,explicit"
)
_FACT_API = "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en"
_TIMEOUT = 8

# Offline safety net — always clean.
_FALLBACK_JOKES = (
    "Why don't scientists trust atoms? Because they make up everything!",
    "What do you call a fish wearing a bowtie? So-fish-ticated!",
    "Why did the math book look sad? Because it had too many problems.",
    "What do you call a bear with no teeth? A gummy bear!",
)
_FALLBACK_FACTS = (
    "Honey never spoils. Archaeologists have found pots of honey in ancient "
    "tombs that are over three thousand years old and still edible.",
    "A group of flamingos is called a flamboyance.",
    "Octopuses have three hearts and blue blood.",
)


class FunSkill(Skill):
    """Tells clean jokes and fun facts."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)
        self._joke_i = 0
        self._fact_i = 0

    @property
    def name(self) -> str:
        return "fun-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        low = (context.utterance or "").lower()
        wants_fact = "fact" in low and "joke" not in low

        if wants_fact:
            text = await self._get_fact(context)
        else:
            text = await self._get_joke(context)
        return SkillResponse(text=text)

    # ------------------------------------------------------------------
    # Jokes
    # ------------------------------------------------------------------

    async def _get_joke(self, context: SkillContext) -> str:
        try:
            joke = await asyncio.to_thread(self._fetch_joke)
            if joke:
                return joke
        except Exception as exc:  # noqa: BLE001
            logger.debug("Joke API failed: %s", exc)

        ai = await self._ai_line(
            "Tell me one short, clean, family-friendly joke suitable for "
            "children. Just the joke, no preamble.",
            context,
        )
        if ai:
            return ai

        joke = _FALLBACK_JOKES[self._joke_i % len(_FALLBACK_JOKES)]
        self._joke_i += 1
        return joke

    @staticmethod
    def _fetch_joke() -> Optional[str]:
        req = urllib.request.Request(_JOKE_API, headers={"User-Agent": "Meryna/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if data.get("error"):
            return None
        if data.get("type") == "twopart":
            setup = data.get("setup", "").strip()
            delivery = data.get("delivery", "").strip()
            if setup and delivery:
                return f"{setup} ... {delivery}"
            return None
        joke = (data.get("joke") or "").strip()
        return joke or None

    # ------------------------------------------------------------------
    # Facts
    # ------------------------------------------------------------------

    async def _get_fact(self, context: SkillContext) -> str:
        try:
            fact = await asyncio.to_thread(self._fetch_fact)
            if fact:
                return f"Here's a fun fact. {fact}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("Fact API failed: %s", exc)

        ai = await self._ai_line(
            "Tell me one short, interesting, family-friendly fun fact. "
            "Just the fact, no preamble.",
            context,
        )
        if ai:
            return f"Here's a fun fact. {ai}"

        fact = _FALLBACK_FACTS[self._fact_i % len(_FALLBACK_FACTS)]
        self._fact_i += 1
        return f"Here's a fun fact. {fact}"

    @staticmethod
    def _fetch_fact() -> Optional[str]:
        req = urllib.request.Request(_FACT_API, headers={"User-Agent": "Meryna/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return (data.get("text") or "").strip() or None

    # ------------------------------------------------------------------
    # AI helper
    # ------------------------------------------------------------------

    async def _ai_line(self, prompt: str, context: SkillContext) -> str:
        if self._ai_provider is None:
            return ""
        try:
            reply = await self._ai_provider.generate_text(
                prompt=prompt,
                conversation_history=context.conversation_history,
            )
            return (reply or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Fun AI line failed: %s", exc)
            return ""
