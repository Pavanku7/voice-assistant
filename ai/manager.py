"""
AIProviderManager — orchestrates primary and fallback AI providers.

Reads primary and (optional) fallback provider configuration from the
:class:`~platform.config.ConfigurationManager`, initialises them within a
30-second budget, and transparently falls back from the primary to the
fallback provider on authentication errors, rate limiting, or connection
timeouts.

Requirements addressed: 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from ai.provider import AIProvider, AIProviderType
from meryna_platform.models import IntentClassification, IntentPattern

logger = logging.getLogger("meryna.ai.manager")

# Timeout for the whole initialize() sequence (Requirements 3.2, 3.3)
_INIT_TIMEOUT_SECONDS: int = 30


class AIProviderManager:
    """Manages AI providers with automatic fallback support.

    Parameters
    ----------
    config_manager:
        The platform :class:`~platform.config.ConfigurationManager` used to
        read the ``ai_provider`` configuration block.
    personality_prompt:
        Meryna's system/personality prompt included in every
        :meth:`generate_text` request (Requirement 3.7).
    """

    def __init__(
        self,
        config_manager: Any,
        personality_prompt: str = "",
    ) -> None:
        self._config = config_manager
        self._personality_prompt = personality_prompt
        self._max_history = 20

        self._primary: Optional[AIProvider] = None
        self._fallback: Optional[AIProvider] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, timeout_seconds: int = _INIT_TIMEOUT_SECONDS) -> bool:
        """Initialise the primary (and optional fallback) provider.

        The whole sequence is bounded by *timeout_seconds* (Requirement 3.2).
        On timeout or connection failure the error is logged and an
        initialization error is reported to the caller (Requirement 3.3).

        Returns
        -------
        bool
            ``True`` if at least the primary provider initialised
            successfully, ``False`` otherwise.
        """
        try:
            return await asyncio.wait_for(
                self._do_initialize(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.error(
                "AIProviderManager initialization timed out after %d seconds.",
                timeout_seconds,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "AIProviderManager initialization failed: %s", exc, exc_info=True
            )
            return False

    async def _do_initialize(self) -> bool:
        """Build and initialise the configured providers."""
        ai_cfg: Dict[str, Any] = self._config.get("ai_provider", {}) or {}

        primary_cfg = ai_cfg.get("primary")
        fallback_cfg = ai_cfg.get("fallback")

        if not primary_cfg:
            logger.error(
                "No primary AI provider configured under 'ai_provider.primary'."
            )
            return False

        # Build primary provider (required)
        self._primary = self._build_provider(primary_cfg)
        if self._primary is None:
            logger.error("Failed to construct the primary AI provider.")
            return False

        try:
            ok = await self._primary.initialize()
            if not ok:
                logger.error("Primary AI provider reported initialization failure.")
                self._primary = None
                return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Primary AI provider raised during init: %s", exc)
            self._primary = None
            return False

        # Build fallback provider (optional — failure is non-fatal)
        if fallback_cfg:
            self._fallback = self._build_provider(fallback_cfg)
            if self._fallback is not None:
                try:
                    if not await self._fallback.initialize():
                        logger.warning(
                            "Fallback AI provider failed to initialise; "
                            "continuing with primary only."
                        )
                        self._fallback = None
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Fallback AI provider raised during init (%s); "
                        "continuing with primary only.",
                        exc,
                    )
                    self._fallback = None

        return True

    # ------------------------------------------------------------------
    # Provider construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_provider(cfg: Dict[str, Any]) -> Optional[AIProvider]:
        """Construct an :class:`AIProvider` from a config block.

        Expected config shape::

            {"type": "claude", "model": "...", "api_key_env": "ANTHROPIC_API_KEY"}
        """
        provider_type = str(cfg.get("type", "")).lower()
        model = cfg.get("model")
        api_key_env = cfg.get("api_key_env", "")
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""

        try:
            if provider_type == AIProviderType.GEMINI.value:
                from ai.gemini import GeminiProvider

                return GeminiProvider(
                    api_key=api_key,
                    model=model or "gemini-2.5-flash",
                )
            if provider_type == AIProviderType.CLAUDE.value:
                from ai.claude import ClaudeProvider

                return ClaudeProvider(
                    api_key=api_key,
                    model=model or "claude-sonnet-4-5",
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Could not construct provider of type %r: %s", provider_type, exc
            )
            return None

        logger.error("Unknown AI provider type: %r", provider_type)
        return None

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_provider(self) -> Optional[AIProvider]:
        """Return the active AI provider (primary if available, else fallback)."""
        return self._primary or self._fallback

    @property
    def has_fallback(self) -> bool:
        """``True`` when a fallback provider is configured and initialised."""
        return self._fallback is not None

    # ------------------------------------------------------------------
    # Operations with automatic fallback
    # ------------------------------------------------------------------

    async def generate_text(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Generate text, falling back to the secondary provider on failure.

        The personality prompt is supplied as the system prompt and the most
        recent :data:`_max_history` turns are passed as context
        (Requirements 3.7, 3.8).

        Raises
        ------
        RuntimeError
            If no provider is available, or if both providers fail
            (Requirement 3.6).
        """
        history = (conversation_history or [])[-self._max_history:]

        async def _call(provider: AIProvider) -> str:
            return await provider.generate_text(
                prompt=prompt,
                conversation_history=history,
                system_prompt=self._personality_prompt or None,
            )

        return await self._run_with_fallback(_call, "generate_text")

    async def classify_intent(
        self,
        user_input: str,
        available_intents: List[IntentPattern],
    ) -> IntentClassification:
        """Classify intent, falling back to the secondary provider on failure.

        Raises
        ------
        RuntimeError
            If no provider is available, or if both providers fail
            (Requirement 3.6).
        """

        async def _call(provider: AIProvider) -> IntentClassification:
            return await provider.classify_intent(user_input, available_intents)

        return await self._run_with_fallback(_call, "classify_intent")

    async def extract_entities(
        self,
        text: str,
        entity_types: Optional[List[str]] = None,
    ):
        """Extract entities, falling back to the secondary provider on failure."""

        async def _call(provider: AIProvider):
            return await provider.extract_entities(text, entity_types)

        return await self._run_with_fallback(_call, "extract_entities")

    # ------------------------------------------------------------------
    # Internal fallback machinery
    # ------------------------------------------------------------------

    async def _run_with_fallback(self, call, operation: str):
        """Run *call* against the primary provider, falling back on failure.

        Fallback is triggered for authentication errors, rate limiting, and
        connection timeouts (Requirement 3.5).  If the fallback is not
        configured or also fails, a ``RuntimeError`` describing the failure is
        raised (Requirement 3.6).
        """
        if self._primary is None and self._fallback is None:
            raise RuntimeError("No AI provider is available.")

        primary_error: Optional[Exception] = None

        if self._primary is not None:
            try:
                return await call(self._primary)
            except Exception as exc:  # noqa: BLE001
                primary_error = exc
                if not self._should_fallback(exc):
                    logger.error(
                        "Primary provider failed on %s with non-retryable "
                        "error: %s",
                        operation,
                        exc,
                    )
                    raise
                logger.warning(
                    "Primary provider failed on %s (%s); attempting fallback.",
                    operation,
                    exc,
                )

        if self._fallback is not None:
            try:
                return await call(self._fallback)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Fallback provider also failed on %s: %s", operation, exc
                )
                raise RuntimeError(
                    f"Both primary and fallback AI providers failed for "
                    f"'{operation}'. Fallback error: {exc}"
                ) from exc

        # No fallback available
        raise RuntimeError(
            f"AI provider failed for '{operation}' and no fallback is "
            f"configured. Error: {primary_error}"
        ) from primary_error

    @staticmethod
    def _should_fallback(exc: Exception) -> bool:
        """Return ``True`` for errors that warrant a fallback attempt.

        Covers authentication errors, rate limiting, and connection timeouts
        (Requirement 3.5).
        """
        exc_type = type(exc).__name__.lower()
        exc_str = str(exc).lower()

        # Status code, if the exception carries one
        status_code: Optional[int] = None
        for attr in ("status_code", "status", "code"):
            val = getattr(exc, attr, None)
            if val is not None:
                try:
                    status_code = int(val)
                    break
                except (TypeError, ValueError):
                    pass

        if status_code in (401, 403, 429) or (
            status_code is not None and 500 <= status_code <= 599
        ):
            return True

        keywords = (
            "auth",
            "unauthorized",
            "forbidden",
            "permission",
            "rate",
            "ratelimit",
            "quota",
            "timeout",
            "timed out",
            "connection",
            "unavailable",
        )
        return any(k in exc_type or k in exc_str for k in keywords) or isinstance(
            exc, (TimeoutError, asyncio.TimeoutError, ConnectionError)
        )
