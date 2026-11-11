"""
IntentRouter — routes user utterances to the appropriate skill.

Uses the AI provider for intent classification with a keyword-matching
fallback if the AI does not respond within 3000 ms or errors.  Selects the
skill with the highest confidence ≥ 0.5, breaking ties by registration order,
and routes to the default ``conversation`` skill when nothing matches.

Requirements addressed: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from meryna_platform.models import IntentPattern, RoutingResult
from skills.base import Skill

logger = logging.getLogger("meryna.skills.router")

# Requirement 2.6 — AI classification must respond within 3000 ms.
_AI_TIMEOUT_SECONDS: float = 3.0

# Requirement 2.3 — minimum confidence for a skill match.
_MIN_CONFIDENCE: float = 0.5


class IntentRouter:
    """Routes utterances to skills using AI intent classification.

    Parameters
    ----------
    ai_provider:
        Provider (or :class:`~ai.manager.AIProviderManager`) exposing an async
        ``classify_intent`` and ``extract_entities`` interface.
    skill_registry:
        The :class:`~skills.registry.SkillRegistry` used to look up intents
        and resolve skills.
    fallback_skill_name:
        Name of the default conversation skill (Requirement 2.3).
    """

    def __init__(
        self,
        ai_provider: Any,
        skill_registry: Any,
        fallback_skill_name: str = "conversation-skill",
    ) -> None:
        self._ai = ai_provider
        self._registry = skill_registry
        self._fallback_skill_name = fallback_skill_name

    # ------------------------------------------------------------------
    # Public routing entry point
    # ------------------------------------------------------------------

    async def route(
        self,
        utterance: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RoutingResult:
        """Route *utterance* to the best-matching skill.

        Tries AI classification first (bounded to 3000 ms); on timeout or
        error, falls back to keyword matching (Requirement 2.6).
        """
        available_intents = self._registry.get_all_intents()

        intent_name = "unknown"
        confidence = 0.0
        entities: Dict[str, Any] = {}
        fallback_used = False

        if available_intents:
            try:
                intent_name, confidence, entities = await asyncio.wait_for(
                    self._classify_intent_with_ai(utterance, available_intents),
                    timeout=_AI_TIMEOUT_SECONDS,
                )
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                logger.warning(
                    "AI intent classification unavailable (%s); "
                    "falling back to keyword matching.",
                    type(exc).__name__,
                )
                fallback_used = True
                intent_name, confidence = self._classify_intent_with_keywords(
                    utterance, available_intents
                )
                entities = self._extract_entities_with_keywords(utterance)

        # Select the skill for the chosen intent.
        skill = self._select_skill(intent_name, confidence, available_intents)

        if skill is None:
            # Route to the default conversation skill (Requirement 2.3).
            skill = self._resolve_fallback_skill()
            intent_name = intent_name if intent_name != "unknown" else "general_chat"
            return RoutingResult(
                skill=skill,
                intent_name=intent_name,
                confidence=confidence,
                entities=entities,
                fallback_used=True,
            )

        return RoutingResult(
            skill=skill,
            intent_name=intent_name,
            confidence=confidence,
            entities=entities,
            fallback_used=fallback_used,
        )

    # ------------------------------------------------------------------
    # AI classification
    # ------------------------------------------------------------------

    async def _classify_intent_with_ai(
        self,
        utterance: str,
        available_intents: List[IntentPattern],
    ) -> Tuple[str, float, Dict[str, Any]]:
        """Classify *utterance* and extract entities using the AI provider."""
        classification = await self._ai.classify_intent(utterance, available_intents)

        entities: Dict[str, Any] = {}
        try:
            extraction = await self._ai.extract_entities(utterance)
            entities = dict(getattr(extraction, "entities", {}) or {})
        except Exception as exc:  # noqa: BLE001
            logger.debug("Entity extraction failed: %s", exc)

        return (
            classification.intent_name,
            float(classification.confidence),
            entities,
        )

    # ------------------------------------------------------------------
    # Keyword fallback
    # ------------------------------------------------------------------

    def _classify_intent_with_keywords(
        self,
        utterance: str,
        available_intents: List[IntentPattern],
    ) -> Tuple[str, float]:
        """Score intents by keyword overlap with their example utterances.

        Returns ``(intent_name, confidence)`` where confidence is a rough
        overlap ratio.  Returns ``("unknown", 0.0)`` when nothing overlaps.
        """
        tokens = self._tokenize(utterance)
        if not tokens:
            return "unknown", 0.0

        best_intent = "unknown"
        best_score = 0.0

        for pattern in available_intents:
            example_tokens: set[str] = set()
            for example in pattern.example_utterances:
                example_tokens |= self._tokenize(example)
            # Include the intent name words as weak signals.
            example_tokens |= self._tokenize(pattern.intent_name.replace("_", " "))

            if not example_tokens:
                continue

            overlap = tokens & example_tokens
            if not overlap:
                continue

            # Confidence: fraction of utterance tokens matched, capped at 0.95.
            score = min(0.95, len(overlap) / max(1, len(tokens)))
            if score > best_score:
                best_score = score
                best_intent = pattern.intent_name

        return best_intent, best_score

    @staticmethod
    def _extract_entities_with_keywords(utterance: str) -> Dict[str, Any]:
        """Very lightweight entity heuristics used only in fallback mode."""
        entities: Dict[str, Any] = {}
        # Capture "in <Location>" / "for <Location>" patterns for weather/maps.
        match = re.search(
            r"\b(?:in|for|at|near)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)",
            utterance,
        )
        if match:
            entities["location"] = match.group(1).strip()
        return entities

    # ------------------------------------------------------------------
    # Skill selection
    # ------------------------------------------------------------------

    def _select_skill(
        self,
        intent_name: str,
        confidence: float,
        available_intents: List[IntentPattern],
    ) -> Optional[Skill]:
        """Select the skill for *intent_name* if confidence ≥ 0.5.

        Ties are broken by registration order because ``get_all_intents``
        preserves it and we scan in that order (Requirement 2.4).
        """
        if intent_name == "unknown" or confidence < _MIN_CONFIDENCE:
            return None

        skill = self._registry.get_skill_for_intent(intent_name)
        return skill

    def _resolve_fallback_skill(self) -> Optional[Skill]:
        """Return the default conversation skill instance, if available."""
        skill = self._registry.get_skill(self._fallback_skill_name)
        if skill is not None:
            return skill

        # As a secondary fallback, try any skill whose name contains "conversation".
        for name in getattr(self._registry, "loaded_skill_names", []):
            if "conversation" in name.lower():
                return self._registry.get_skill(name)

        logger.warning(
            "No fallback conversation skill '%s' is loaded.",
            self._fallback_skill_name,
        )
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Lower-case word tokens with trivial stop-word removal."""
        stop = {
            "the", "a", "an", "is", "are", "do", "does", "to", "of", "in",
            "on", "at", "for", "and", "or", "me", "my", "i", "you", "what",
            "whats", "s", "please", "can", "could", "would",
        }
        words = re.findall(r"[a-zA-Z]+", text.lower())
        return {w for w in words if w not in stop and len(w) > 1}
