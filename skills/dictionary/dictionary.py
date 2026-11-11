"""
DictionarySkill — word meanings, spelling, and examples (no API key).

Uses the free ``dictionaryapi.dev`` service to fetch a word's definition, part
of speech, and an example sentence. Falls back to asking the AI provider to
define the word if the dictionary service has no entry (e.g. proper nouns or
newer terms), so the skill still gives a useful answer.

Requirements addressed: 7.2, 7.5, 7.6, 7.8
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Optional

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.dictionary")

_API = "https://api.dictionaryapi.dev/api/v2/entries/en/"
_TIMEOUT = 8

# Words we strip to isolate the term the user actually wants defined.
_STOPWORDS = {
    "what", "whats", "what's", "does", "do", "the", "word", "mean", "means",
    "meaning", "of", "define", "definition", "is", "a", "an", "how", "you",
    "spell", "give", "me", "another", "for", "tell", "about",
}


class DictionarySkill(Skill):
    """Defines words and gives spelling and examples."""

    def __init__(self, ai_provider: Any) -> None:
        super().__init__(ai_provider)

    @property
    def name(self) -> str:
        return "dictionary-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        word = self._extract_word(context)
        if not word:
            return SkillResponse(
                text="Which word would you like me to define?",
                follow_up_prompt="What word should I look up?",
            )

        try:
            entry = await asyncio.to_thread(self._lookup, word)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Dictionary lookup error for %r: %s", word, exc)
            entry = None

        if entry:
            return SkillResponse(text=entry)

        # No dictionary entry — let the AI try to define it.
        ai_reply = await self._ai_definition(word, context)
        if ai_reply:
            return SkillResponse(text=ai_reply)

        return SkillResponse(
            text=f"I couldn't find a definition for '{word}'. "
            "Could you check the spelling?"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_word(self, context: SkillContext) -> str:
        entities = context.entities or {}
        for key in ("word", "term", "query"):
            val = entities.get(key)
            if val:
                return str(val).strip().strip("?.!,'\"")

        # Fall back to stripping filler words from the utterance.
        text = (context.utterance or "").lower()
        text = re.sub(r"[^\w\s']", " ", text)
        tokens = [t for t in text.split() if t and t not in _STOPWORDS]
        # Use the last remaining token(s) — usually the target word.
        return tokens[-1] if tokens else ""

    @staticmethod
    def _lookup(word: str) -> Optional[str]:
        """Fetch and format a definition from dictionaryapi.dev (blocking).

        The free service occasionally returns a transient 502, so one retry is
        made before giving up (a genuine 404 for an unknown word is not
        retried, since urllib raises the same HTTPError type we then treat as
        "no entry" either way).
        """
        url = _API + urllib.parse.quote(word)
        req = urllib.request.Request(url, headers={"User-Agent": "Meryna/1.0"})
        data = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="replace"))
                break
            except urllib.error.HTTPError as exc:
                # 404 == word not found; anything else may be transient.
                if exc.code == 404 or attempt == 1:
                    return None
            except Exception:  # noqa: BLE001
                if attempt == 1:
                    return None
        if data is None:
            return None

        if not isinstance(data, list) or not data:
            return None

        first = data[0]
        term = first.get("word", word)
        meanings = first.get("meanings") or []
        if not meanings:
            return None

        meaning = meanings[0]
        part = meaning.get("partOfSpeech", "")
        defs = meaning.get("definitions") or []
        if not defs:
            return None

        definition = defs[0].get("definition", "").strip()
        example = defs[0].get("example", "").strip()

        spelled = "-".join(term.upper())
        parts = [f"{term}"]
        if part:
            parts.append(f"({part})")
        sentence = " ".join(parts) + f": {definition}"
        if example:
            sentence += f" For example: {example}"
        sentence += f" It's spelled {spelled}."
        return sentence

    async def _ai_definition(self, word: str, context: SkillContext) -> str:
        if self._ai_provider is None:
            return ""
        prompt = (
            f"Define the word or term '{word}' in one or two simple sentences "
            "suitable for reading aloud. Include its part of speech if it's a "
            "common word, and a short example. Reply in the user's language."
        )
        try:
            reply = await self._ai_provider.generate_text(
                prompt=prompt,
                conversation_history=context.conversation_history,
            )
            return (reply or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("AI definition failed: %s", exc)
            return ""
