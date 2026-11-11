"""
AI Provider abstract base class and type definitions.

Defines the unified interface that all AI backend implementations must satisfy,
along with the AIProviderType enum for supported providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

from meryna_platform.models import EntityExtraction, IntentClassification, IntentPattern


class AIProviderType(Enum):
    """Supported AI provider backends."""

    GEMINI = "gemini"
    CLAUDE = "claude"


class AIProvider(ABC):
    """
    Abstract base class for AI provider implementations.

    All concrete providers (Gemini, Claude, …) must subclass this and
    implement each abstract method.  The unified interface covers three
    primary NLU operations plus lifecycle management:

    1. ``generate_text``     — open-ended text generation
    2. ``classify_intent``   — map a user utterance to a known intent
    3. ``extract_entities``  — pull named entities from free-form text
    4. ``initialize``        — connect and warm up the underlying backend
    5. ``health_check``      — verify the backend is reachable and responsive

    All methods are declared ``async`` so implementations can use
    non-blocking I/O (httpx, aiohttp, native SDK async clients, etc.)
    without any adapter boilerplate.
    """

    # ------------------------------------------------------------------
    # Text generation
    # ------------------------------------------------------------------

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        """
        Generate a text response for the given prompt.

        Parameters
        ----------
        prompt:
            The user-facing input to respond to.
        conversation_history:
            Recent conversation turns in ``[{"role": ..., "content": ...}]``
            format.  Implementations should include at most the last 20
            turns (Requirement 3.8).
        system_prompt:
            Optional system-level instruction that shapes the model's
            persona and behaviour.  Must not exceed 4 000 characters
            (Requirement 3.7).
        max_tokens:
            Upper bound on the number of tokens to generate.

        Returns
        -------
        str
            The generated text response.
        """

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    @abstractmethod
    async def classify_intent(
        self,
        user_input: str,
        available_intents: List[IntentPattern],
    ) -> IntentClassification:
        """
        Classify *user_input* into one of the provided intents.

        Parameters
        ----------
        user_input:
            Raw utterance from the user.
        available_intents:
            All intent patterns currently registered with the platform.
            Each entry contains the skill name, intent name, description,
            and example utterances the model can use as guidance.

        Returns
        -------
        IntentClassification
            The matched intent name, a confidence score in [0.0, 1.0],
            and the raw model response for debugging.
        """

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------

    @abstractmethod
    async def extract_entities(
        self,
        text: str,
        entity_types: Optional[List[str]] = None,
    ) -> EntityExtraction:
        """
        Extract named entities from *text*.

        Parameters
        ----------
        text:
            The input text to analyse.
        entity_types:
            Optional list of entity type names to look for (e.g.
            ``["location", "date", "person"]``).  When ``None`` the
            provider should extract all entity types it recognises.

        Returns
        -------
        EntityExtraction
            A dict-like container mapping entity type names to their
            extracted values (e.g. ``{"location": "Bengaluru"}``).
        """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(self) -> bool:
        """
        Initialise and connect to the underlying AI backend.

        Must complete within 30 seconds; callers are responsible for
        enforcing that timeout (Requirement 3.2, 3.3).

        Returns
        -------
        bool
            ``True`` if initialisation succeeded, ``False`` otherwise.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verify that the provider is healthy and can accept requests.

        Returns
        -------
        bool
            ``True`` if the provider is responsive, ``False`` otherwise.
        """
