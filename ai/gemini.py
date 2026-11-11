"""
GeminiProvider — Google Gemini AI backend for the Meryna Voice Platform.

Wraps the ``google-genai`` client (same client used in the legacy Meryna.py)
and exposes the unified :class:`~ai.provider.AIProvider` interface so the
rest of the platform can remain backend-agnostic.

Environment variable
--------------------
``GEMINI_API_KEY``  – API key injected by the caller or read from the
                      process environment as a convenience default.

Requirements satisfied
----------------------
3.1  Unified interface: generate_text, classify_intent, extract_entities
3.2  initialize() completes within 30 s (enforced via asyncio.wait_for)
3.3  Log failure and raise on timeout or connection error
3.7  System prompt included in every generate_text call (max 4 000 chars)
3.8  Last 20 messages of conversation history included in generate_text
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from ai.provider import AIProvider
from meryna_platform.models import EntityExtraction, IntentClassification, IntentPattern

logger = logging.getLogger(__name__)

# Maximum characters allowed for the system prompt (Requirement 3.7)
_MAX_SYSTEM_PROMPT_CHARS: int = 4_000

# How many recent conversation turns to include (Requirement 3.8)
_MAX_HISTORY_TURNS: int = 20

# Timeout for initialize() in seconds (Requirements 3.2, 3.3)
_INIT_TIMEOUT_SECONDS: int = 30


class GeminiProvider(AIProvider):
    """Google Gemini AI provider implementation.

    Parameters
    ----------
    api_key:
        Gemini API key.  Defaults to the ``GEMINI_API_KEY`` environment
        variable when not supplied explicitly.
    model:
        Gemini model name (default ``"gemini-2.5-flash"``).
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-2.5-flash",
    ) -> None:
        self._api_key: str = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._model: str = model
        self._client: Optional[genai.Client] = None
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Initialize the Gemini client with a 30-second timeout.

        Performs a lightweight test call to verify connectivity.  Logs the
        failure and raises on timeout or connection error (Requirement 3.3).

        Returns
        -------
        bool
            ``True`` on success.  Raises on failure — never silently returns
            ``False`` so the caller can rely on exceptions for error handling.

        Raises
        ------
        asyncio.TimeoutError
            If the initialization does not complete within 30 seconds.
        RuntimeError
            If the API key is missing or the connection cannot be established.
        """
        try:
            result = await asyncio.wait_for(
                self._do_initialize(),
                timeout=_INIT_TIMEOUT_SECONDS,
            )
            return result
        except asyncio.TimeoutError:
            logger.error(
                "GeminiProvider initialization timed out after %d seconds.",
                _INIT_TIMEOUT_SECONDS,
            )
            raise
        except Exception as exc:
            logger.error(
                "GeminiProvider initialization failed: %s", exc, exc_info=True
            )
            raise

    async def _do_initialize(self) -> bool:
        """Internal coroutine that performs the actual initialization."""
        if not self._api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. "
                "Provide it via the constructor or the GEMINI_API_KEY "
                "environment variable."
            )

        # Build the client (synchronous; non-blocking in practice)
        self._client = genai.Client(api_key=self._api_key)

        # Verify connectivity with a minimal test call
        await self._run_in_executor(
            self._client.models.generate_content,
            model=self._model,
            contents=[{"role": "user", "parts": [{"text": "ping"}]}],
            config=types.GenerateContentConfig(max_output_tokens=1),
        )

        self._initialized = True
        logger.info(
            "GeminiProvider initialized successfully (model=%s).", self._model
        )
        return True

    async def health_check(self) -> bool:
        """Send a minimal request to verify the provider is responsive.

        Returns
        -------
        bool
            ``True`` if the provider responds, ``False`` otherwise.
        """
        try:
            await self._run_in_executor(
                self._client.models.generate_content,
                model=self._model,
                contents=[{"role": "user", "parts": [{"text": "ping"}]}],
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            return True
        except Exception as exc:
            logger.warning("GeminiProvider health check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Text generation (Requirement 3.7, 3.8)
    # ------------------------------------------------------------------

    async def generate_text(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        """Generate a text response using Gemini.

        Parameters
        ----------
        prompt:
            The current user utterance.
        conversation_history:
            List of ``{"role": "user"|"assistant", "content": "..."}`` dicts.
            Only the last :data:`_MAX_HISTORY_TURNS` entries are sent
            (Requirement 3.8).
        system_prompt:
            Optional system-level instruction.  Truncated to
            :data:`_MAX_SYSTEM_PROMPT_CHARS` characters (Requirement 3.7).
        max_tokens:
            Upper bound on generated tokens.

        Returns
        -------
        str
            The generated text, stripped of leading/trailing whitespace.
        """
        self._ensure_initialized()

        # Truncate system prompt (Requirement 3.7)
        truncated_system: Optional[str] = None
        if system_prompt:
            truncated_system = system_prompt[:_MAX_SYSTEM_PROMPT_CHARS]
            if len(system_prompt) > _MAX_SYSTEM_PROMPT_CHARS:
                logger.debug(
                    "System prompt truncated from %d to %d characters.",
                    len(system_prompt),
                    _MAX_SYSTEM_PROMPT_CHARS,
                )

        # Build contents list: history + current prompt
        contents = self._build_contents(
            prompt=prompt,
            conversation_history=conversation_history,
        )

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
        )
        if truncated_system:
            config = types.GenerateContentConfig(
                system_instruction=truncated_system,
                max_output_tokens=max_tokens,
            )

        logger.debug(
            "GeminiProvider.generate_text: model=%s turns=%d",
            self._model,
            len(contents),
        )

        response = await self._run_in_executor(
            self._client.models.generate_content,
            model=self._model,
            contents=contents,
            config=config,
        )

        reply = (response.text or "").strip()
        logger.debug("GeminiProvider.generate_text reply length=%d", len(reply))
        return reply

    # ------------------------------------------------------------------
    # Intent classification (Requirement 3.1)
    # ------------------------------------------------------------------

    async def classify_intent(
        self,
        user_input: str,
        available_intents: List[IntentPattern],
    ) -> IntentClassification:
        """Classify *user_input* into one of the *available_intents*.

        Sends a structured JSON prompt to Gemini and parses the response.

        Returns
        -------
        IntentClassification
            Contains ``intent_name``, ``confidence`` (0.0–1.0), and the
            ``raw_response`` string from the model.
        """
        self._ensure_initialized()

        intents_description = self._format_intents_for_prompt(available_intents)

        prompt = (
            "You are an intent classifier for a voice assistant.\n\n"
            "Available intents:\n"
            f"{intents_description}\n\n"
            f'User utterance: "{user_input}"\n\n'
            "Respond with a JSON object (no markdown, no code fences) with "
            "exactly these fields:\n"
            '  "intent_name": the matched intent name (string),\n'
            '  "confidence": a float between 0.0 and 1.0,\n'
            '  "reasoning": a brief explanation (string)\n\n'
            "If none of the intents match, use "
            '"intent_name": "unknown" with a low confidence.'
        )

        logger.debug(
            "GeminiProvider.classify_intent: input=%r intents=%d",
            user_input[:80],
            len(available_intents),
        )

        raw_response = await self._run_in_executor(
            self._client.models.generate_content,
            model=self._model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(max_output_tokens=256),
        )

        raw_text = (raw_response.text or "").strip()

        intent_name, confidence = self._parse_intent_response(
            raw_text, available_intents
        )

        logger.debug(
            "GeminiProvider.classify_intent result: intent=%s confidence=%.2f",
            intent_name,
            confidence,
        )

        return IntentClassification(
            intent_name=intent_name,
            confidence=confidence,
            raw_response=raw_text,
        )

    # ------------------------------------------------------------------
    # Entity extraction (Requirement 3.1)
    # ------------------------------------------------------------------

    async def extract_entities(
        self,
        text: str,
        entity_types: Optional[List[str]] = None,
    ) -> EntityExtraction:
        """Extract named entities from *text*.

        Parameters
        ----------
        text:
            Free-form input to analyse.
        entity_types:
            Optional list of entity type names to look for.  When ``None``
            the model extracts all entity types it recognises.

        Returns
        -------
        EntityExtraction
            A container with an ``entities`` dict mapping type names to values.
        """
        self._ensure_initialized()

        if entity_types:
            types_instruction = (
                "Extract ONLY the following entity types "
                f"(if present): {', '.join(entity_types)}."
            )
        else:
            types_instruction = (
                "Extract all named entities you can identify "
                "(locations, dates, times, names, numbers, etc.)."
            )

        prompt = (
            "You are an entity extractor for a voice assistant.\n\n"
            f"{types_instruction}\n\n"
            f'Input text: "{text}"\n\n'
            "Respond with a JSON object (no markdown, no code fences) where "
            "keys are entity type names and values are the extracted values. "
            "Example: {\"location\": \"Bengaluru\", \"date\": \"tomorrow\"}. "
            "If no entities are found, respond with {}."
        )

        logger.debug(
            "GeminiProvider.extract_entities: text=%r types=%s",
            text[:80],
            entity_types,
        )

        raw_response = await self._run_in_executor(
            self._client.models.generate_content,
            model=self._model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=types.GenerateContentConfig(max_output_tokens=256),
        )

        raw_text = (raw_response.text or "").strip()
        entities = self._parse_json_dict(raw_text)

        logger.debug(
            "GeminiProvider.extract_entities result: %s", entities
        )

        return EntityExtraction(entities=entities)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        """Raise if the provider has not been successfully initialized."""
        if not self._initialized or self._client is None:
            raise RuntimeError(
                "GeminiProvider has not been initialized. "
                "Call initialize() before using the provider."
            )

    def _build_contents(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, Any]]:
        """Build the Gemini ``contents`` list from history + current prompt.

        Limits history to the last :data:`_MAX_HISTORY_TURNS` turns
        (Requirement 3.8).  The current ``prompt`` is appended as the final
        user message.
        """
        contents: List[Dict[str, Any]] = []

        if conversation_history:
            # Take only the last _MAX_HISTORY_TURNS entries
            recent = conversation_history[-_MAX_HISTORY_TURNS:]
            for turn in recent:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                # Gemini uses "model" for assistant turns
                gemini_role = "model" if role == "assistant" else "user"
                contents.append(
                    {"role": gemini_role, "parts": [{"text": content}]}
                )

        # Append the current user prompt
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        return contents

    @staticmethod
    def _format_intents_for_prompt(intents: List[IntentPattern]) -> str:
        """Return a human-readable list of intents for use in a prompt."""
        lines: List[str] = []
        for i, intent in enumerate(intents, start=1):
            examples = ", ".join(
                f'"{u}"' for u in (intent.example_utterances or [])[:3]
            )
            lines.append(
                f"{i}. {intent.intent_name} ({intent.skill_name}): "
                f"{intent.description}. "
                f"Examples: {examples}"
            )
        return "\n".join(lines) if lines else "(no intents registered)"

    @staticmethod
    def _parse_intent_response(
        raw_text: str,
        available_intents: List[IntentPattern],
    ) -> tuple[str, float]:
        """Parse Gemini's JSON intent-classification response.

        Falls back gracefully to ``("unknown", 0.0)`` on any parse error.
        """
        data = GeminiProvider._parse_json_dict(raw_text)
        if not data:
            return "unknown", 0.0

        intent_name: str = str(data.get("intent_name", "unknown")).strip()
        try:
            confidence: float = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        # Clamp to [0, 1]
        confidence = max(0.0, min(1.0, confidence))

        # Validate that the returned intent name exists in the registered list
        valid_names = {p.intent_name for p in available_intents}
        if intent_name not in valid_names:
            logger.debug(
                "Gemini returned unrecognised intent %r; falling back to 'unknown'.",
                intent_name,
            )
            intent_name = "unknown"
            confidence = 0.0

        return intent_name, confidence

    @staticmethod
    def _parse_json_dict(text: str) -> Dict[str, Any]:
        """Attempt to parse a JSON dict from *text*.

        Strips markdown code fences before parsing.  Returns ``{}`` on
        failure.
        """
        # Strip ```json ... ``` or ``` ... ``` fences
        cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()

        # Try to locate the first {...} block
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]

        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            logger.debug(
                "GeminiProvider._parse_json_dict failed to parse: %r", text[:200]
            )
        return {}

    @staticmethod
    async def _run_in_executor(fn, *args, **kwargs) -> Any:
        """Run a synchronous *fn* in the default thread-pool executor.

        The ``google-genai`` SDK's ``models.generate_content`` is synchronous,
        so we offload it to avoid blocking the event loop.  Keyword arguments
        are supported because the SDK's ``generate_content`` is keyword-only
        (``model=``, ``contents=``, ``config=``).
        """
        loop = asyncio.get_event_loop()
        call = functools.partial(fn, *args, **kwargs)
        return await loop.run_in_executor(None, call)
