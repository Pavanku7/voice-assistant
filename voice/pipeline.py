"""
VoicePipeline — manages voice input/output with swappable engines.

Loads the configured STT and TTS engines from the Configuration Manager,
supports hot-swapping engines without restart, and degrades gracefully to
text mode with a notification when speech input or output fails.

Requirements addressed: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from meryna_platform.models import VoiceConfig
from voice.stt.base import STTEngine, STTEngineType
from voice.tts.base import TTSEngine, TTSEngineType

logger = logging.getLogger("meryna.voice.pipeline")

# Barge-in tuning: how long each "listen while speaking" window waits for the
# user to start talking, and the most speech to capture once they do.
_BARGEIN_LISTEN_WINDOW = 2  # seconds to wait for speech onset per window
_BARGEIN_MAX_DURATION = 15  # seconds of the interrupting utterance to capture


@dataclass
class VoiceResult:
    """Outcome of a :meth:`VoicePipeline.listen` / :meth:`speak` call."""

    ok: bool
    text: Optional[str] = None
    fell_back: bool = False
    notification: Optional[str] = None


class VoicePipeline:
    """Manages voice input/output with swappable STT/TTS engines.

    Parameters
    ----------
    config_manager:
        The platform :class:`~platform.config.ConfigurationManager`.
    """

    def __init__(self, config_manager: Any) -> None:
        self._config = config_manager
        self._stt_engine: Optional[STTEngine] = None
        self._tts_engine: Optional[TTSEngine] = None
        self._voice_config = VoiceConfig()
        self._voice_enabled = True
        self._fallback_to_text = True

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Load the configured STT and TTS engines and voice config."""
        vp_cfg = self._config.get("voice_pipeline", {}) or {}

        # Voice configuration.
        vc = vp_cfg.get("voice_config", {}) or {}
        self._voice_config = VoiceConfig(
            gender=vc.get("gender", "female"),
            language=vc.get("language", "en-IN"),
            speech_rate=int(vc.get("speech_rate", 165)),
            volume=float(vc.get("volume", 0.9)),
            voice_id=vc.get("voice_id"),
        )

        stt_name = vp_cfg.get("stt_engine", STTEngineType.GOOGLE.value)
        tts_name = vp_cfg.get("tts_engine", STTEngineType.GOOGLE.value)

        self.set_stt_engine(stt_name)
        self.set_tts_engine(vp_cfg.get("tts_engine", TTSEngineType.EDGE_TTS.value))

        # tts_name computed above is unused; keep for clarity of config keys.
        _ = tts_name
        return True

    # ------------------------------------------------------------------
    # Engine selection (hot-swap — Requirements 4.1, 4.2)
    # ------------------------------------------------------------------

    def set_stt_engine(self, engine_type: Any) -> bool:
        """Switch the STT engine at runtime without restart."""
        engine_type = self._coerce_stt_type(engine_type)
        try:
            if engine_type == STTEngineType.GOOGLE:
                from voice.stt.google import GoogleSTTEngine

                self._stt_engine = GoogleSTTEngine(language=self._voice_config.language)
            elif engine_type == STTEngineType.WHISPER:
                from voice.stt.whisper import WhisperSTTEngine

                self._stt_engine = WhisperSTTEngine()
            elif engine_type == STTEngineType.WEB_SPEECH:
                from voice.stt.web_speech import WebSpeechSTTEngine

                self._stt_engine = WebSpeechSTTEngine(
                    language=self._voice_config.language
                )
            else:
                logger.error("Unknown STT engine type: %r", engine_type)
                return False
            logger.info("STT engine set to %s.", engine_type.value)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to set STT engine %r: %s", engine_type, exc)
            return False

    def set_tts_engine(self, engine_type: Any) -> bool:
        """Switch the TTS engine at runtime without restart."""
        engine_type = self._coerce_tts_type(engine_type)
        try:
            if engine_type == TTSEngineType.EDGE_TTS:
                from voice.tts.edge_tts import EdgeTTSEngine

                self._tts_engine = EdgeTTSEngine(config=self._voice_config)
            elif engine_type == TTSEngineType.PYTTSX3:
                from voice.tts.pyttsx3 import Pyttsx3TTSEngine

                self._tts_engine = Pyttsx3TTSEngine(config=self._voice_config)
            elif engine_type == TTSEngineType.BROWSER:
                from voice.tts.browser import BrowserTTSEngine

                self._tts_engine = BrowserTTSEngine(config=self._voice_config)
            else:
                logger.error("Unknown TTS engine type: %r", engine_type)
                return False
            self._tts_engine.configure(self._voice_config)
            logger.info("TTS engine set to %s.", engine_type.value)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to set TTS engine %r: %s", engine_type, exc)
            return False

    # ------------------------------------------------------------------
    # Listen / speak with graceful degradation
    # ------------------------------------------------------------------

    async def listen(self) -> VoiceResult:
        """Capture voice input, falling back to text mode on failure.

        On unavailable microphone / network timeout / recognition error the
        pipeline signals a text-input fallback with a notification message
        (Requirement 4.6).
        """
        if self._stt_engine is None:
            return VoiceResult(
                ok=False,
                fell_back=True,
                notification="Voice input is not configured. Please type instead.",
            )

        if not self._stt_engine.is_available():
            return VoiceResult(
                ok=False,
                fell_back=True,
                notification=(
                    "Microphone is unavailable. Falling back to text input."
                ),
            )

        try:
            text = await self._stt_engine.transcribe(timeout=5, max_duration=15)
            if text:
                return VoiceResult(ok=True, text=text)
            # No speech detected — not an error, just nothing heard.
            return VoiceResult(ok=False, text=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("VoicePipeline.listen failed: %s", exc)
            return VoiceResult(
                ok=False,
                fell_back=True,
                notification=(
                    "Speech recognition failed. Falling back to text input."
                ),
            )

    def is_speaking(self) -> bool:
        """Return ``True`` while the TTS engine is actively playing audio."""
        engine = self._tts_engine
        checker = getattr(engine, "is_speaking", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:  # noqa: BLE001
                return False
        return False

    def stop_speaking(self) -> None:
        """Immediately stop any in-progress spoken output."""
        engine = self._tts_engine
        if engine is not None:
            try:
                engine.stop()
            except Exception:  # noqa: BLE001
                pass

    async def speak_interruptible(self, text: str) -> VoiceResult:
        """Speak *text* while listening for a barge-in (Alexa-style interrupt).

        Playback starts non-blocking; meanwhile the microphone listens in short
        windows.  If the user starts speaking before playback finishes, the
        audio is stopped immediately and the recognised words are returned in
        :attr:`VoiceResult.text` so the caller can treat them as the next
        request.

        Returns
        -------
        VoiceResult
            * ``ok=True, text=<words>`` — the user interrupted; *text* is what
              they said (the next utterance to process).
            * ``ok=True, text=None`` — playback finished without interruption.
            * otherwise — falls back to a plain (blocking) ``speak`` result if
              barge-in isn't supported in the current setup.
        """
        if not self._voice_enabled:
            return VoiceResult(ok=True, text=None)

        tts = self._tts_engine
        stt = self._stt_engine
        supports_bargein = (
            tts is not None
            and tts.is_available()
            and callable(getattr(tts, "is_speaking", None))
            and stt is not None
            and stt.is_available()
        )

        # No barge-in support (e.g. pyttsx3/browser or no mic) → plain speak.
        if not supports_bargein:
            return await self.speak(text)

        # 1. Start playback without blocking.
        try:
            started = await tts.speak(text, block=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("speak_interruptible: playback failed: %s", exc)
            return VoiceResult(ok=False, text=text, fell_back=True)

        if not started:
            return VoiceResult(ok=False, text=text, fell_back=True)

        # 2. While audio plays, listen in short windows for a barge-in.
        try:
            while self.is_speaking():
                heard = await stt.transcribe(
                    timeout=_BARGEIN_LISTEN_WINDOW,
                    max_duration=_BARGEIN_MAX_DURATION,
                )
                if not self.is_speaking():
                    break  # Finished naturally during the listen window.
                if heard:
                    # User interrupted — cut the audio and hand back their words.
                    self.stop_speaking()
                    logger.info("Barge-in detected: %r", heard)
                    return VoiceResult(ok=True, text=heard)
        except Exception as exc:  # noqa: BLE001
            logger.debug("speak_interruptible listen loop error: %s", exc)

        # 3. Playback completed with no interruption.
        return VoiceResult(ok=True, text=None)

    async def speak(self, text: str) -> VoiceResult:
        """Speak *text* via the TTS engine, falling back to text-only mode.

        On unavailable audio output / init error / synthesis error the pipeline
        signals a text-only fallback with a notification (Requirement 4.7).
        """
        if not self._voice_enabled:
            return VoiceResult(ok=False, text=text)

        if self._tts_engine is None or not self._tts_engine.is_available():
            return VoiceResult(
                ok=False,
                text=text,
                fell_back=True,
                notification=(
                    "Audio output is unavailable. Showing text response only."
                ),
            )

        try:
            spoke = await self._tts_engine.speak(text, block=True)
            if spoke:
                return VoiceResult(ok=True, text=text)
            return VoiceResult(
                ok=False,
                text=text,
                fell_back=True,
                notification=(
                    "Voice synthesis failed. Showing text response only."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("VoicePipeline.speak failed: %s", exc)
            return VoiceResult(
                ok=False,
                text=text,
                fell_back=True,
                notification=(
                    "Voice synthesis failed. Showing text response only."
                ),
            )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure_voice(self, config: VoiceConfig) -> None:
        """Apply a new voice configuration to the active TTS engine.

        Enforces the documented ranges: speech rate 50–300 wpm and volume
        0.0–1.0 (Requirement 4.5).
        """
        config.speech_rate = max(50, min(300, int(config.speech_rate)))
        config.volume = max(0.0, min(1.0, float(config.volume)))
        self._voice_config = config
        if self._tts_engine is not None:
            self._tts_engine.configure(config)

    def enable_voice(self, enabled: bool) -> None:
        """Enable or disable spoken output."""
        self._voice_enabled = enabled

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def voice_config(self) -> VoiceConfig:
        return self._voice_config

    @property
    def voice_enabled(self) -> bool:
        return self._voice_enabled

    def get_stt_engine(self) -> Optional[STTEngine]:
        return self._stt_engine

    def get_tts_engine(self) -> Optional[TTSEngine]:
        return self._tts_engine

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_stt_type(value: Any) -> STTEngineType:
        if isinstance(value, STTEngineType):
            return value
        try:
            return STTEngineType(str(value))
        except ValueError:
            return STTEngineType.GOOGLE

    @staticmethod
    def _coerce_tts_type(value: Any) -> TTSEngineType:
        if isinstance(value, TTSEngineType):
            return value
        try:
            return TTSEngineType(str(value))
        except ValueError:
            return TTSEngineType.EDGE_TTS
