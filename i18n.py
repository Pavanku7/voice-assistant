"""
i18n — lightweight language auto-detection for Meryna (English / Hindi / Nepali).

Meryna runs in **auto-detect only** mode: there is no language setting. Instead
Meryna figures out which language the user is speaking and replies in the same
language, and the TTS engine picks a matching neural voice on the fly.

This module is a leaf utility with no project dependencies, so both the voice
engines (``voice/tts/*``) and the skills (``skills/*``) can import it without
creating a layering cycle.

Detection strategy (best-effort, offline, zero-cost):
  * No Devanagari characters            -> English  ("en")
  * Devanagari present                  -> Hindi or Nepali, disambiguated by a
                                           small set of marker words unique to
                                           each language (they share the script).
    Ambiguous Devanagari defaults to Hindi (the more common of the two here).

The AI models (Gemini/Claude) are multilingual, so replying in-language is
handled by an instruction added to the personality prompt; this module only
supplies that instruction text and the correct voice / STT codes.
"""

from __future__ import annotations

import re

# Language codes used throughout Meryna.
ENGLISH = "en"
HINDI = "hi"
NEPALI = "ne"

DEFAULT_LANGUAGE = ENGLISH

# Any character in the Devanagari Unicode block (U+0900–U+097F) plus the
# extended block (U+A8E0–U+A8FF) marks Hindi/Nepali text.
_DEVANAGARI = re.compile(r"[ऀ-ॿ꣠-ꣿ]")

# Marker words that appear in one language but not (or rarely) the other.
# Hindi and Nepali share the Devanagari script, so we lean on these to tell
# them apart. Matched as substrings against the raw text.
_NEPALI_MARKERS = (
    "छ",       # "chha" — the Nepali copula, extremely common
    "छन्",
    "हो",      # "ho" — is
    "होइन",
    "गर्नु",   # to do
    "गरेको",
    "तपाईं",   # you (formal)
    "तपाइँ",
    "कस्तो",   # how / what kind
    "मलाई",    # to me
    "हामी",    # we
    "भयो",     # happened / became
    "राम्रो",  # good
    "अहिले",   # now
    "किन",     # why (Nepali spelling context)
    "सञ्चै",   # fine / well
)

_HINDI_MARKERS = (
    "है",      # is
    "हैं",
    "क्या",    # what
    "आप",      # you (formal)
    "कैसे",    # how
    "मुझे",    # to me
    "हम",      # we
    "क्यों",   # why
    "नहीं",    # no / not
    "अच्छा",   # good
    "अभी",     # now
    "मैं",     # I
    "और",      # and
    "हुआ",     # happened
)

# Edge-TTS neural voices per language and gender.
_VOICES = {
    ENGLISH: {"female": "en-IN-NeerjaNeural", "male": "en-IN-PrabhatNeural"},
    HINDI:   {"female": "hi-IN-SwaraNeural",  "male": "hi-IN-MadhurNeural"},
    NEPALI:  {"female": "ne-NP-HemkalaNeural", "male": "ne-NP-SagarNeural"},
}

# BCP-47 codes for speech-to-text (Google Web Speech / browser recognition).
_STT_CODES = {
    ENGLISH: "en-IN",
    HINDI: "hi-IN",
    NEPALI: "ne-NP",
}

# Human-readable names (used in prompts / logs).
LANGUAGE_NAMES = {
    ENGLISH: "English",
    HINDI: "Hindi",
    NEPALI: "Nepali",
}


def detect_language(text: str) -> str:
    """Return the detected language code for *text* (``en`` / ``hi`` / ``ne``).

    Best-effort and cheap: script check first, then marker words to split
    Hindi from Nepali. Empty or non-Devanagari text is treated as English.
    """
    if not text:
        return DEFAULT_LANGUAGE

    if not _DEVANAGARI.search(text):
        return ENGLISH

    # Devanagari present -> Hindi or Nepali. Count marker hits for each.
    nepali_hits = sum(1 for m in _NEPALI_MARKERS if m in text)
    hindi_hits = sum(1 for m in _HINDI_MARKERS if m in text)

    if nepali_hits > hindi_hits:
        return NEPALI
    if hindi_hits > nepali_hits:
        return HINDI

    # Tie (including no markers matched): default to Hindi.
    return HINDI


def voice_for_language(language: str, gender: str = "female") -> str:
    """Return the edge-tts neural voice id for *language* and *gender*."""
    lang = language if language in _VOICES else DEFAULT_LANGUAGE
    by_gender = _VOICES[lang]
    return by_gender.get(gender, by_gender["female"])


def stt_code(language: str) -> str:
    """Return the BCP-47 STT code for *language* (e.g. ``hi-IN``)."""
    return _STT_CODES.get(language, _STT_CODES[DEFAULT_LANGUAGE])


def language_name(language: str) -> str:
    """Return the human-readable name for a language code."""
    return LANGUAGE_NAMES.get(language, "English")


# Instruction appended to Meryna's personality prompt so every AI-generated
# reply comes back in whatever language the user just used.
LANGUAGE_INSTRUCTION = (
    "Meryna is multilingual and supports English, Hindi, and Nepali. "
    "Detect the language the user is writing or speaking in and ALWAYS reply "
    "in that same language. If the user writes in Hindi (Devanagari), reply in "
    "natural Hindi. If they write in Nepali (Devanagari), reply in natural "
    "Nepali. If they write in English, reply in English. Do not mix languages "
    "in a single reply unless the user did. Never translate the user's message "
    "back to them unless they explicitly ask for a translation."
)
