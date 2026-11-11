"""
GoogleSTTEngine — desktop STT via the ``SpeechRecognition`` library.

Wraps ``speech_recognition``'s Google Web Speech backend.  Waits up to
``timeout`` seconds for speech to begin and captures up to ``max_duration``
seconds of continuous speech (Requirement 4.3).  Microphone discovery mirrors
the robust device-probing logic from the legacy ``Meryna.py``.

Requirements addressed: 4.1, 4.3
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from voice.stt.base import STTEngine

logger = logging.getLogger("meryna.voice.stt.google")


class GoogleSTTEngine(STTEngine):
    """Google Speech Recognition STT engine (desktop microphone).

    Parameters
    ----------
    language:
        BCP-47 language code passed to ``recognize_google`` (default
        ``"en-IN"``).
    """

    def __init__(self, language: str = "en-IN") -> None:
        self._language = language
        self._recognizer = None
        self._mic = None
        self._available = False
        self._init_recognizer()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_recognizer(self) -> None:
        """Create the recognizer and locate a working microphone."""
        try:
            import speech_recognition as sr
        except ImportError:
            logger.warning(
                "SpeechRecognition is not installed; GoogleSTTEngine unavailable."
            )
            return

        try:
            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = True
            self._mic = self._find_microphone(sr)
            self._available = self._mic is not None
        except Exception as exc:  # noqa: BLE001
            logger.warning("GoogleSTTEngine initialisation failed: %s", exc)
            self._available = False

    @staticmethod
    def _find_microphone(sr):
        """Probe available input devices and return the first that opens.

        Returns ``None`` if no working microphone is found.
        """
        try:
            mic_names = sr.Microphone.list_microphone_names()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not enumerate microphones: %s", exc)
            return None

        recognizer = sr.Recognizer()
        for index, name in enumerate(mic_names):
            if any(
                tag in name
                for tag in ("Output", "Speaker", "Stereo Mix", "Mapper")
            ):
                continue
            try:
                test_mic = sr.Microphone(device_index=index)
                with test_mic as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.3)
                logger.info("GoogleSTTEngine connected to mic [%d]: %s", index, name)
                return test_mic
            except Exception:  # noqa: BLE001
                continue

        # Last resort: default microphone.
        try:
            default_mic = sr.Microphone()
            with default_mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
            return default_mic
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # STTEngine interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return self._available and self._mic is not None

    async def transcribe(
        self,
        timeout: int = 5,
        max_duration: int = 15,
    ) -> Optional[str]:
        """Listen once and return the transcript (or ``None``).

        The blocking ``SpeechRecognition`` calls run in a thread so the event
        loop is never blocked.
        """
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
            text = self._recognizer.recognize_google(audio, language=self._language)
            return text.strip() or None
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("GoogleSTTEngine transcription error: %s", exc)
            return None
