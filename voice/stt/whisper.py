"""
WhisperSTTEngine — offline STT via ``openai-whisper``.

Captures audio from the desktop microphone using ``speech_recognition`` and
transcribes it locally with a Whisper model.  Whisper is optional; the engine
reports ``is_available() == False`` when the package or a microphone is
missing so the Voice Pipeline can fall back cleanly.

Requirements addressed: 4.1, 4.3
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from voice.stt.base import STTEngine

logger = logging.getLogger("meryna.voice.stt.whisper")


class WhisperSTTEngine(STTEngine):
    """OpenAI Whisper STT engine (offline, desktop microphone).

    Parameters
    ----------
    model_name:
        Whisper model size to load (``"tiny"``, ``"base"``, ``"small"``, …).
        Smaller models load faster and use less memory.
    language:
        Optional language hint passed to the recogniser.
    """

    def __init__(self, model_name: str = "base", language: str = "en") -> None:
        self._model_name = model_name
        self._language = language
        self._recognizer = None
        self._mic = None
        self._available = False
        self._init()

    def _init(self) -> None:
        try:
            import speech_recognition as sr  # noqa: F401
            import whisper  # noqa: F401
        except ImportError:
            logger.warning(
                "openai-whisper / SpeechRecognition not installed; "
                "WhisperSTTEngine unavailable."
            )
            return

        try:
            import speech_recognition as sr

            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = True
            try:
                self._mic = sr.Microphone()
                with self._mic as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
            except Exception as exc:  # noqa: BLE001
                logger.warning("WhisperSTTEngine microphone unavailable: %s", exc)
                self._mic = None
            self._available = self._mic is not None
        except Exception as exc:  # noqa: BLE001
            logger.warning("WhisperSTTEngine initialisation failed: %s", exc)
            self._available = False

    def is_available(self) -> bool:
        return self._available and self._mic is not None

    async def transcribe(
        self,
        timeout: int = 5,
        max_duration: int = 15,
    ) -> Optional[str]:
        if not self.is_available():
            return None
        return await asyncio.to_thread(self._blocking_transcribe, timeout, max_duration)

    def _blocking_transcribe(self, timeout: int, max_duration: int) -> Optional[str]:
        import speech_recognition as sr

        try:
            with self._mic as source:
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=max_duration,
                )
            # SpeechRecognition exposes a Whisper wrapper: recognize_whisper.
            text = self._recognizer.recognize_whisper(
                audio,
                model=self._model_name,
                language=self._language,
            )
            return (text or "").strip() or None
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("WhisperSTTEngine transcription error: %s", exc)
            return None
