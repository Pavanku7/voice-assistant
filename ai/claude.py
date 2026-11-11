"""
ClaudeProvider — Anthropic Claude backend for the Meryna AI provider layer.

Wraps the synchronous ``anthropic`` client (used in meryna_brain.py) behind
the async ``AIProvider`` interface.  All blocking SDK calls are dispatched to a
thread-pool via ``asyncio.to_thread`` so the event loop is never blocked.

Requirements addressed: 3.1, 3.2, 3.3, 3.7, 3.8
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import anthropic

from ai.provider import AIProvider
from meryna_platform.models import EntityExtraction, IntentClassification, IntentPattern

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INITIALIZE_TIMEOUT_SECONDS = 30
_MAX_SYSTEM_PROMPT_CHARS = 4000
_MAX_HISTORY_TURNS = 20


class ClaudeProvider(AIProvider):
    """
    Anthropic Claude implementation of :class:`AIProvider`.

    Parameters
    ----------
    api_key:
        Anthropic API key.  Usually sourced from the ``ANTHROPIC_API_KEY``
        environment variable.
    model:
        Claude model identifier.  Defaults to ``"claude-sonnet-4-5"``.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Optional[anthropic.Anthropic] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """
        Instantiate and warm up the Anthropic client.

        Sends a minimal test message to verify that the API key is valid and
        the backend is reachable.  Enforces a 30-second timeout via
        ``asyncio.wait_for`` (Requirement 3.2, 3.3).

        Returns
        -------
        bool
            ``True`` on success, ``False`` on timeout or connection failure.
        """
        try:
            await asyncio.wait_for(
                self._do_initialize(),
                timeout=_INITIALIZE_TIMEOUT_SECONDS,
            )
            logger.info(
                "ClaudeProvider initialised successfully (model=%s).", self._model
            )
            return True
        except asyncio.TimeoutError:
            logger.error(
                "ClaudeProvider initialization timed out after %s seconds.",
                _INITIALIZE_TIMEOUT_SECONDS,
            )
            return False
        except anthropic.AuthenticationError as exc:
            logger.error("ClaudeProvider authentication failed: %s", exc)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("ClaudeProvider initialization error: %s", exc)
            return False

    async def _do_initialize(self) -> None:
        """Create client and perform a lightweight connectivity probe."""

        def _create_client() -> anthropic.Anthropic:
            return anthropic.Anthropic(api_key=self._api_key)

        self._client = await asyncio.to_thread(_create_client)

        # Lightweight probe: single-token response to validate credentials.
        def _probe() -> None:
            self._client.messages.create(  # type: ignore[union-attr]
                model=self._model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )

        await asyncio.to_thread(_probe)

    async def health_check(self) -> bool:
        """
        Verify the provider is reachable and responsive.

        Returns
        -------
        bool
            ``True`` if a test request succeeds, ``False`` otherwise.
        """
        if self._client is None:
            return False
        try:

            def _check() -> None:
                self._client.messages.create(  # type: ignore[union-attr]
                    model=self._model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                )

            await asyncio.to_thread(_check)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("ClaudeProvider health check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Text generation  (Requirement 3.1, 3.7, 3.8)
    # ------------------------------------------------------------------

    async def generate_text(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        """
        Generate a text response using Claude.

        The system prompt is truncated to :data:`_MAX_SYSTEM_PROMPT_CHARS`
        characters (Requirement 3.7).  At most the last
        :data:`_MAX_HISTORY_TURNS` conversation turns are included as context
        (Requirement 3.8).

        Parameters
        ----------
        prompt:
            Current user utterance.
        conversation_history:
            Prior conversation turns in ``[{"role": ..., "content": ...}]``
            format.
        system_prompt:
            Optional personality / instruction prompt (≤ 4000 chars).
        max_tokens:
            Maximum tokens to generate.

        Returns
        -------
        str
            Generated text, or an empty string on failure.
        """
        self._ensure_client()

        # Truncate system prompt to 4000 chars (Requirement 3.7)
        effective_system: Optional[str] = None
        if system_prompt:
            effective_system = system_prompt[:_MAX_SYSTEM_PROMPT_CHARS]

        # Build message list from history (last 20 turns) + current prompt
        messages = self._build_messages(prompt, conversation_history)

        def _call() -> str:
            kwargs: Dict[str, Any] = {
                "model": self._model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if effective_system:
                kwargs["system"] = effective_system

            response = self._client.messages.create(**kwargs)  # type: ignore[union-attr]
            parts = [
                block.text
                for block in response.content
                if hasattr(block, "text")
            ]
            return "\n".join(parts).strip()

        try:
            result: str = await asyncio.to_thread(_call)
            logger.debug(
                "ClaudeProvider.generate_text: prompt_len=%d reply_len=%d",
                len(prompt),
                len(result),
            )
            return result
        except anthropic.RateLimitError as exc:
            logger.warning("ClaudeProvider rate limited: %s", exc)
            raise
        except anthropic.AuthenticationError as exc:
            logger.error("ClaudeProvider auth error in generate_text: %s", exc)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("ClaudeProvider.generate_text failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Intent classification  (Requirement 3.1)
    # ------------------------------------------------------------------

    async def classify_intent(
        self,
        user_input: str,
        available_intents: List[IntentPattern],
    ) -> IntentClassification:
        """
        Classify *user_input* into one of the provided intent patterns.

        Sends a structured JSON prompt to Claude and parses the response back
        into an :class:`IntentClassification`.

        Returns
        -------
        IntentClassification
            The matched intent, a confidence in [0.0, 1.0], and the raw
            model response.
        """
        self._ensure_client()

        intents_description = "\n".join(
            f'- intent_name: "{ip.intent_name}" | skill: "{ip.skill_name}" | '
            f'description: "{ip.description}" | '
            f'examples: {ip.example_utterances[:3]}'
            for ip in available_intents
        )

        classification_prompt = (
            "You are an intent classifier. Given the user utterance below and the "
            "list of available intents, respond ONLY with a valid JSON object "
            "(no markdown, no explanation) with the following fields:\n"
            '  "intent_name": <string — the matched intent_name from the list>,\n'
            '  "confidence": <float between 0.0 and 1.0>,\n'
            '  "reason": <one-sentence explanation>\n\n'
            f"Available intents:\n{intents_description}\n\n"
            f'User utterance: "{user_input}"\n\n'
            "Respond with JSON only."
        )

        messages = [{"role": "user", "content": classification_prompt}]

        def _call() -> str:
            response = self._client.messages.create(  # type: ignore[union-attr]
                model=self._model,
                max_tokens=256,
                messages=messages,
            )
            parts = [
                block.text
                for block in response.content
                if hasattr(block, "text")
            ]
            return "\n".join(parts).strip()

        try:
            raw: str = await asyncio.to_thread(_call)
            intent_name, confidence = self._parse_classification(raw, available_intents)
            return IntentClassification(
                intent_name=intent_name,
                confidence=confidence,
                raw_response=raw,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("ClaudeProvider.classify_intent failed: %s", exc)
            # Return a low-confidence fallback so the router can handle it
            fallback_intent = available_intents[0].intent_name if available_intents else "unknown"
            return IntentClassification(
                intent_name=fallback_intent,
                confidence=0.0,
                raw_response=str(exc),
            )

    # ------------------------------------------------------------------
    # Entity extraction  (Requirement 3.1)
    # ------------------------------------------------------------------

    async def extract_entities(
        self,
        text: str,
        entity_types: Optional[List[str]] = None,
    ) -> EntityExtraction:
        """
        Extract named entities from *text*.

        Sends a structured JSON prompt to Claude and parses the response back
        into an :class:`EntityExtraction`.

        Returns
        -------
        EntityExtraction
            Mapping of entity type → extracted value.  Returns empty entities
            dict on failure.
        """
        self._ensure_client()

        types_hint = (
            f"Focus on these entity types: {', '.join(entity_types)}."
            if entity_types
            else "Extract all entity types you recognise (e.g. location, date, person, organisation, quantity)."
        )

        extraction_prompt = (
            "You are a named-entity extractor. Given the text below, respond ONLY "
            "with a valid JSON object (no markdown, no explanation) where the keys "
            "are entity type names and the values are the extracted strings. If an "
            "entity type is not present, omit it from the object.\n\n"
            f"{types_hint}\n\n"
            f'Text: "{text}"\n\n'
            "Respond with JSON only."
        )

        messages = [{"role": "user", "content": extraction_prompt}]

        def _call() -> str:
            response = self._client.messages.create(  # type: ignore[union-attr]
                model=self._model,
                max_tokens=256,
                messages=messages,
            )
            parts = [
                block.text
                for block in response.content
                if hasattr(block, "text")
            ]
            return "\n".join(parts).strip()

        try:
            raw: str = await asyncio.to_thread(_call)
            entities = self._parse_json_object(raw)
            return EntityExtraction(entities=entities)
        except Exception as exc:  # noqa: BLE001
            logger.error("ClaudeProvider.extract_entities failed: %s", exc)
            return EntityExtraction(entities={})

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> None:
        """Raise ``RuntimeError`` if the client has not been initialised."""
        if self._client is None:
            raise RuntimeError(
                "ClaudeProvider has not been initialised. "
                "Call await provider.initialize() first."
            )

    def _build_messages(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        """
        Construct the messages list for the API call.

        Includes at most the last :data:`_MAX_HISTORY_TURNS` turns from
        *conversation_history*, then appends the current *prompt* as a user
        message (Requirement 3.8).
        """
        messages: List[Dict[str, str]] = []

        if conversation_history:
            recent = conversation_history[-_MAX_HISTORY_TURNS:]
            for turn in recent:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _parse_json_object(raw: str) -> Dict[str, Any]:
        """
        Extract a JSON object from *raw*, stripping markdown fences if present.

        Returns an empty dict if parsing fails.
        """
        # Strip ```json ... ``` fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        # Find the first { ... } block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.debug("ClaudeProvider: could not parse JSON from: %r", raw[:200])
            return {}

    def _parse_classification(
        self,
        raw: str,
        available_intents: List[IntentPattern],
    ) -> tuple[str, float]:
        """
        Parse the classification JSON response.

        Returns
        -------
        tuple[str, float]
            ``(intent_name, confidence)`` — falls back to the first available
            intent with 0.0 confidence if parsing fails.
        """
        data = self._parse_json_object(raw)
        intent_name: str = data.get("intent_name", "")
        confidence: float = float(data.get("confidence", 0.0))

        # Validate that returned intent actually exists
        valid_names = {ip.intent_name for ip in available_intents}
        if intent_name not in valid_names:
            logger.warning(
                "ClaudeProvider: classified intent %r not in available intents; "
                "defaulting to first.",
                intent_name,
            )
            intent_name = available_intents[0].intent_name if available_intents else "unknown"
            confidence = 0.0

        # Clamp confidence to [0.0, 1.0]
        confidence = max(0.0, min(1.0, confidence))
        return intent_name, confidence
