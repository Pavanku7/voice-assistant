"""
Pyttsx3TTSEngine — offline text-to-speech via ``pyttsx3``.

Auto-selects a female system voice, applies rate/volume from the voice
configuration, and strips markdown before speaking — mirroring the legacy
``meryna_voice.speak_text`` behaviour.

Requirements addressed: 4.2, 4.4, 4.5
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from meryna_platform.models import VoiceConfig
from voice.tts.base import TTSEngine

logger = logging.getLogger("meryna.voice.tts.pyttsx3")

_FEMALE_HINTS = (
    "female", "woman", "zira", "samantha", "karen",
    "victoria", "hazel", "susan", "neerja",
)


class Pyttsx3TTSEngine(TTSEngine):
    """Offline pyttsx3 TTS engine (auto-selects a female voice)."""

    def __init__(self, config: Optional[VoiceConfig] = None) -> None:
        self._config = config or VoiceConfig()
        self._available = self._check_available()

    def _check_available(self) -> bool:
        try:
            import pyttsx3  # noqa: F401
            return True
        except ImportError:
            logger.warning("pyttsx3 is not installed; Pyttsx3TTSEngine unavailable.")
            return False

    # ------------------------------------------------------------------
    # TTSEngine interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return self._available

    def configure(self, config: VoiceConfig) -> None:
        self._config = config

    def stop(self) -> None:
        # pyttsx3 runs each utterance in a fresh engine instance (below), so
        # there is no persistent playback to stop mid-flight.
        pass

    async def speak(self, text: str, block: bool = True) -> bool:
        if not self.is_available():
            return False
        clean = self._clean_text(text)
        if not clean:
            return True
        return await asyncio.to_thread(self._blocking_speak, clean)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _blocking_speak(self, clean: str) -> bool:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", int(self._config.speech_rate))
            engine.setProperty("volume", float(self._config.volume))
            self._select_voice(engine)
            engine.say(clean)
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:  # noqa: BLE001
                pass
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pyttsx3TTSEngine synthesis error: %s", exc)
            return False

    def _select_voice(self, engine) -> None:
        try:
            voices = engine.getProperty("voices")
        except Exception:  # noqa: BLE001
            return

        if self._config.voice_id:
            for v in voices:
                if v.id == self._config.voice_id:
                    engine.setProperty("voice", v.id)
                    return

        if self._config.gender == "female":
            for v in voices:
                if any(hint in v.name.lower() for hint in _FEMALE_HINTS):
                    engine.setProperty("voice", v.id)
                    return
            # Index 1 is commonly a female voice on Windows.
            if len(voices) > 1:
                engine.setProperty("voice", voices[1].id)

    @staticmethod
    def _clean_text(text: str) -> str:
        clean = (
            text.replace("*", "")
            .replace("_", "")
            .replace("#", "")
            .replace("`", "")
        )
        return clean.strip()
