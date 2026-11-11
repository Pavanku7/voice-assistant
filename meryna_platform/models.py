"""
Shared data models for the Meryna Voice Platform.

All dataclasses and enums used across platform components are defined here
to avoid circular imports and provide a single source of truth for types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ErrorCategory(Enum):
    """Categories of platform errors, used to drive user-facing messaging."""

    SKILL_ERROR = "skill_error"
    AI_RATE_LIMIT = "ai_rate_limit"
    AI_AUTH_ERROR = "ai_auth_error"
    NETWORK_ERROR = "network_error"
    CONFIG_ERROR = "config_error"
    VOICE_ERROR = "voice_error"


# ---------------------------------------------------------------------------
# Platform-level models
# ---------------------------------------------------------------------------


@dataclass
class PlatformResponse:
    """Response returned by the platform after processing a user utterance."""

    text: str
    skill_name: Optional[str]
    confidence: float
    metadata: Dict[str, Any]
    error: Optional[str] = None


@dataclass
class PlatformError:
    """
    User-safe error representation.

    ``user_message`` is safe to display directly to the user and must never
    contain stack traces, file paths, function names, or API credentials.
    ``internal_message`` is for logging only.
    """

    category: ErrorCategory
    user_message: str
    internal_message: str
    service_name: Optional[str] = None
    retryable: bool = False


# ---------------------------------------------------------------------------
# Skill execution models
# ---------------------------------------------------------------------------


@dataclass
class SkillContext:
    """Context passed to a skill's ``execute()`` method."""

    utterance: str
    intent_name: str
    entities: Dict[str, Any]
    conversation_history: List[Dict[str, str]]
    user_preferences: Dict[str, Any]
    session_id: str


@dataclass
class SkillResponse:
    """Response produced by a skill after execution."""

    text: str
    should_end_session: bool = False
    follow_up_prompt: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillConfig:
    """Configuration record for a single skill."""

    name: str
    enabled: bool
    settings: Dict[str, Any]


# ---------------------------------------------------------------------------
# Intent routing models
# ---------------------------------------------------------------------------


@dataclass
class IntentPattern:
    """
    Describes a single intent that a skill can handle.

    Used by the Intent Router to match utterances to skills.
    """

    skill_name: str
    intent_name: str
    description: str
    example_utterances: List[str]


@dataclass
class RoutingResult:
    """Result produced by the Intent Router after processing an utterance."""

    # Circular import guard: 'Skill' is referenced as a string annotation.
    skill: Optional[Any]  # type: skills.base.Skill at runtime
    intent_name: str
    confidence: float  # 0.0 – 1.0
    entities: Dict[str, Any]
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# AI provider models
# ---------------------------------------------------------------------------


@dataclass
class IntentClassification:
    """Result of intent classification performed by an AI provider."""

    intent_name: str
    confidence: float  # 0.0 – 1.0
    raw_response: str


@dataclass
class EntityExtraction:
    """
    Named entities extracted from a piece of text.

    Example::

        EntityExtraction(entities={"location": "Bengaluru", "date": "tomorrow"})
    """

    entities: Dict[str, Any]


# ---------------------------------------------------------------------------
# Voice pipeline models
# ---------------------------------------------------------------------------


@dataclass
class VoiceConfig:
    """
    Voice output configuration applied to TTS engines.

    Attributes
    ----------
    gender:
        Preferred voice gender – ``"male"`` or ``"female"``.
    language:
        BCP-47 language/locale code (e.g. ``"en-IN"``).
    speech_rate:
        Words per minute in the range 50–300.
    volume:
        Output volume in the range 0.0–1.0.
    voice_id:
        Optional engine-specific voice identifier.
    """

    gender: str = "female"
    language: str = "en-IN"
    speech_rate: int = 165
    volume: float = 0.9
    voice_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Memory and context models
# ---------------------------------------------------------------------------


@dataclass
class UserPreferences:
    """Persisted user preferences managed by the Memory Manager."""

    name: str = "Friend"          # max 50 characters
    location: str = ""            # max 100 characters (city, region)
    voice_id: Optional[str] = None
    speech_rate: int = 165        # 50–300 wpm
    volume: float = 0.9           # 0.0–1.0


@dataclass
class ConversationTurn:
    """A single turn in the conversation history."""

    role: str              # "user" or "assistant"
    content: str
    timestamp: float       # Unix epoch seconds
    skill_name: Optional[str] = None


@dataclass
class ConversationState:
    """
    Ephemeral conversation state maintained by the Context Manager.

    Cleared when the platform shuts down or ``ContextManager.clear_state()``
    is called; does not persist to disk.
    """

    active_skill: Optional[str] = None
    follow_up_queue: List[str] = field(default_factory=list)  # max 5 items
    session_data: Dict[str, Any] = field(default_factory=dict)
