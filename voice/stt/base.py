"""
STTEngine — abstract base class for speech-to-text engines.

Concrete engines (Google Speech Recognition, Whisper, browser Web Speech API)
implement :meth:`transcribe` and :meth:`is_available` so the Voice Pipeline can
swap between them without restart.

Requirements addressed: 4.1, 4.3
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class STTEngineType(Enum):
    """Supported speech-to-text engine identifiers."""

    GOOGLE = "google"
    WHISPER = "whisper"
    WEB_SPEECH = "web_speech"


class STTEngine(ABC):
    """Abstract base for speech-to-text engines."""

    @abstractmethod
    async def transcribe(
        self,
        timeout: int = 5,
        max_duration: int = 15,
    ) -> Optional[str]:
        """Capture speech and return the transcript.

        Parameters
        ----------
        timeout:
            Seconds to wait for speech to *begin* (Requirement 4.3).
        max_duration:
            Maximum seconds of continuous speech to capture (Requirement 4.3).

        Returns
        -------
        Optional[str]
            The transcribed text, or ``None`` on silence/timeout/failure.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Return ``True`` if the engine can be used in the current environment."""
