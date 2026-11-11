"""
TTSEngine — abstract base class for text-to-speech engines.

Concrete engines (Edge TTS, pyttsx3, browser synthesis) implement
:meth:`speak`, :meth:`stop`, :meth:`is_available`, and :meth:`configure` so
the Voice Pipeline can swap between them without restart.

Requirements addressed: 4.2, 4.4, 4.5
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from meryna_platform.models import VoiceConfig


class TTSEngineType(Enum):
    """Supported text-to-speech engine identifiers."""

    EDGE_TTS = "edge_tts"
    PYTTSX3 = "pyttsx3"
    BROWSER = "browser"


class TTSEngine(ABC):
    """Abstract base for text-to-speech engines."""

    @abstractmethod
    async def speak(self, text: str, block: bool = True) -> bool:
        """Speak *text*.

        Parameters
        ----------
        text:
            The text to synthesise.
        block:
            When ``True`` the call returns only after playback finishes.

        Returns
        -------
        bool
            ``True`` if speech was produced, ``False`` on failure.
        """

    @abstractmethod
    def stop(self) -> None:
        """Stop any in-progress playback."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return ``True`` if the engine can be used in the current environment."""

    @abstractmethod
    def configure(self, config: VoiceConfig) -> None:
        """Apply a :class:`~platform.models.VoiceConfig` to the engine."""
