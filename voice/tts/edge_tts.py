"""
EdgeTTSEngine — Microsoft Edge neural TTS with pygame playback.

Wraps ``edge-tts`` to synthesise natural neural voices, saving to a temporary
MP3 and playing it through the ``pygame`` mixer — the same approach as the
legacy ``VoiceEngine`` in ``Meryna.py``.

Requirements addressed: 4.2, 4.4, 4.5
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from typing import Optional

from meryna_platform.models import VoiceConfig
from voice.tts.base import TTSEngine

logger = logging.getLogger("meryna.voice.tts.edge")

# Default Indian-English neural voices by gender.
_FEMALE_VOICE = "en-IN-NeerjaNeural"
_MALE_VOICE = "en-IN-PrabhatNeural"

# Words-per-minute treated as edge-tts's natural (0%) speaking rate.  The
# configured ``speech_rate`` is expressed relative to this baseline and sent to
# edge-tts as a percentage (e.g. 210 wpm → "+40%" ≈ 1.4x speed).
_BASELINE_WPM = 150


class EdgeTTSEngine(TTSEngine):
    """Edge TTS engine using neural voices and a pygame mixer for playback."""

    def __init__(self, config: Optional[VoiceConfig] = None) -> None:
        self._config = config or VoiceConfig()
        self._voice = self._voice_for(self._config)
        self._mixer_ready = False
        self._available = self._init_mixer()
        # Temp MP3 of the utterance currently playing (for non-blocking mode);
        # cleaned up by stop() or when the next utterance starts.
        self._current_tmp: Optional[str] = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_mixer(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._mixer_ready = True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("EdgeTTSEngine unavailable (%s).", exc)
            return False

    @staticmethod
    def _voice_for(config: VoiceConfig) -> str:
        if config.voice_id:
            return config.voice_id
        return _MALE_VOICE if config.gender == "male" else _FEMALE_VOICE

    def _voice_for_text(self, text: str) -> str:
        """Pick a neural voice matching the language of *text*.

        Meryna auto-detects language per reply, so a Hindi answer is spoken by
        a Hindi voice and a Nepali answer by a Nepali voice — without any
        setting. An explicit ``voice_id`` in the config overrides this.
        """
        if self._config.voice_id:
            return self._config.voice_id
        try:
            import i18n

            language = i18n.detect_language(text)
            return i18n.voice_for_language(language, self._config.gender)
        except Exception:  # noqa: BLE001 — fall back to the configured voice.
            return self._voice

    # ------------------------------------------------------------------
    # TTSEngine interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return self._available and self._mixer_ready

    def configure(self, config: VoiceConfig) -> None:
        self._config = config
        self._voice = self._voice_for(config)

    def stop(self) -> None:
        try:
            import pygame

            if pygame.mixer.get_init():
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        if self._current_tmp:
            self._cleanup(self._current_tmp)
            self._current_tmp = None

    def is_speaking(self) -> bool:
        """Return ``True`` while audio is actively playing."""
        try:
            import pygame

            return bool(pygame.mixer.get_init() and pygame.mixer.music.get_busy())
        except Exception:  # noqa: BLE001
            return False

    async def speak(self, text: str, block: bool = True) -> bool:
        if not self.is_available():
            return False

        clean = self._clean_text(text)
        if not clean:
            return True  # Nothing to say is not a failure.

        try:
            import edge_tts
            import pygame

            # Clear any leftover temp file from a previous non-blocking call.
            if self._current_tmp:
                self._cleanup(self._current_tmp)
                self._current_tmp = None

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tmp.close()

            communicate = edge_tts.Communicate(
                clean, self._voice_for_text(clean), rate=self._rate_string()
            )
            await communicate.save(tmp.name)

            volume = max(0.0, min(1.0, self._config.volume))
            pygame.mixer.music.load(tmp.name)
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.play()

            if block:
                # Blocking wait offloaded to a thread.
                await asyncio.to_thread(self._wait_until_done)
                self._cleanup(tmp.name)
            else:
                # Non-blocking: return immediately so the caller can listen for
                # a barge-in while audio plays. Remember the temp file so
                # stop()/the next speak() can clean it up.
                self._current_tmp = tmp.name
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("EdgeTTSEngine synthesis error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rate_string(self) -> str:
        """Convert the configured words-per-minute to an edge-tts rate string.

        edge-tts expects a signed percentage relative to its natural pace
        (e.g. ``"+40%"``).  A ``speech_rate`` of :data:`_BASELINE_WPM` maps to
        ``"+0%"``; higher values speak faster.  Clamped to a sane range so a
        stray config value can't make speech unintelligible.
        """
        try:
            wpm = int(self._config.speech_rate)
        except (TypeError, ValueError):
            wpm = _BASELINE_WPM
        percent = round((wpm - _BASELINE_WPM) / _BASELINE_WPM * 100)
        percent = max(-50, min(100, percent))
        return f"{percent:+d}%"

    @staticmethod
    def _wait_until_done() -> None:
        import pygame

        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        try:
            pygame.mixer.music.unload()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _cleanup(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    @staticmethod
    def _clean_text(text: str) -> str:
        clean = text.replace("**", "").replace("*", "").replace("#", "")
        clean = re.sub(r"[^\w\s\.,!?'\-]", "", clean)
        return clean.strip()
