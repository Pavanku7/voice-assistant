"""
Platform — the central orchestrator for the Meryna Voice Platform.

Wires together the Configuration Manager, Platform Logger, Error Handler,
Memory Manager, Context Manager, AI Provider Manager, Skill Registry, Intent
Router, and Voice Pipeline, and exposes :meth:`process_utterance` as the single
entry point shared by every interface (web and CLI).

Requirements addressed: 1.7, 1.8, 8.1, 8.7, 11.4
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from meryna_platform.config import ConfigurationManager
from meryna_platform.errors import ErrorHandler
from meryna_platform.logging import PlatformLogger
from meryna_platform.models import PlatformResponse, SkillContext, SkillResponse

logger = logging.getLogger("meryna.platform.core")


# Default JARVIS-inspired personality prompt (≤ 4000 chars — Requirement 3.7).
DEFAULT_PERSONALITY_PROMPT = (
    "You are Meryna, a highly intelligent AI assistant inspired by J.A.R.V.I.S "
    "from Iron Man. You are calm, confident, professional, and warm. "
    "Address the user by their name when you know it (they will tell you their "
    "name in conversation); never call them 'Boss' or any other generic title. "
    "If you do not yet know their name, simply speak to them directly without "
    "using any name. In a flowing, continuous conversation you may occasionally "
    "open with a short natural acknowledgement like 'hmm', 'ahh', or 'right, I'm "
    "listening' instead of a name, so it feels like a real chat. "
    "Give concrete, useful, concise answers. Never use markdown symbols like "
    "asterisks or headers, because they break the text-to-speech engine. Use a "
    "conversational Indian English tone and keep replies short and easy to "
    "listen to."
)


def _default_config() -> dict:
    """Return the default platform configuration block."""
    return {
        "ai_provider": {
            "primary": {
                "type": "gemini",
                "model": "gemini-2.5-flash",
                "api_key_env": "GEMINI_API_KEY",
            },
            "fallback": {
                "type": "claude",
                "model": "claude-sonnet-4-5",
                "api_key_env": "ANTHROPIC_API_KEY",
            },
        },
        "voice_pipeline": {
            "stt_engine": "google",
            "tts_engine": "edge_tts",
            "voice_config": {
                "gender": "female",
                "language": "en-IN",
                "speech_rate": 180,
                "volume": 0.9,
            },
        },
        "memory": {"storage_path": None, "history_limit": 30},
        "logging": {"level": "INFO", "log_dir": None},
        "personality_prompt": DEFAULT_PERSONALITY_PROMPT,
    }


class Platform:
    """Core platform orchestrator.

    Parameters
    ----------
    config_path:
        Optional directory that holds ``meryna_config.json``.  Defaults to the
        user's home directory.
    skills_dir:
        Optional path to the ``skills/`` directory.  Defaults to the ``skills``
        folder next to this package.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        skills_dir: Optional[Path] = None,
    ) -> None:
        self._config_dir = config_path
        self._skills_dir = (
            Path(skills_dir)
            if skills_dir is not None
            else Path(__file__).resolve().parent.parent / "skills"
        )

        # Components (initialised in start()).
        self.config: Optional[ConfigurationManager] = None
        self.platform_logger: Optional[PlatformLogger] = None
        self.error_handler: Optional[ErrorHandler] = None
        self.memory: Any = None
        self.context: Any = None
        self.ai_manager: Any = None
        self.registry: Any = None
        self.router: Any = None
        self.voice: Any = None

        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """Initialise every component in dependency order.

        Returns
        -------
        bool
            ``True`` if the platform started (AI provider may still be
            degraded); ``False`` on a fatal configuration error.
        """
        # 0a. Use the OS trust store for TLS so corporate/root certificates are
        #     honoured (mirrors legacy Meryna.py; fixes edge-tts / API SSL errors).
        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:  # noqa: BLE001 — truststore is optional.
            pass

        # 0b. Load API keys from .env, if present (mirrors legacy behaviour).
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except Exception:  # noqa: BLE001 — dotenv is optional.
            pass

        # 1. Configuration.
        self.config = ConfigurationManager(config_dir=self._config_dir)
        self.config.load()
        self._ensure_defaults()

        # 2. Logging.
        log_level = self._resolve_log_level()
        self.platform_logger = PlatformLogger(level=log_level)

        # 3. Error handling.
        self.error_handler = ErrorHandler(self.platform_logger)

        # 4. Memory + context.
        from memory.manager import MemoryManager
        from memory.context import ContextManager

        mem_cfg = self.config.get("memory", {}) or {}
        storage_path = mem_cfg.get("storage_path")
        history_limit = int(mem_cfg.get("history_limit", 30))
        self.memory = MemoryManager(
            storage_path=Path(storage_path) if storage_path else None,
            history_limit=history_limit,
        )
        self.memory.load()
        self.context = ContextManager(self.memory)

        # 5. AI provider manager.
        from ai.manager import AIProviderManager

        personality = self.config.get("personality_prompt", DEFAULT_PERSONALITY_PROMPT)
        # Auto-detect language mode: every reply comes back in whatever language
        # (English / Hindi / Nepali) the user just used.
        try:
            import i18n

            personality = f"{personality}\n\n{i18n.LANGUAGE_INSTRUCTION}"
        except Exception:  # noqa: BLE001 — language support is best-effort.
            pass
        self.ai_manager = AIProviderManager(self.config, personality_prompt=personality)
        ai_ok = await self.ai_manager.initialize()
        if not ai_ok:
            self.platform_logger.log_error(
                "AI provider manager failed to initialise; AI features degraded."
            )

        # 6. Skill registry + router.
        from skills.registry import SkillRegistry
        from skills.router import IntentRouter

        self.registry = SkillRegistry(
            skills_dir=self._skills_dir,
            config_manager=self.config,
            ai_provider=self.ai_manager,
        )
        await self.registry.load_all()

        self.router = IntentRouter(
            ai_provider=self.ai_manager,
            skill_registry=self.registry,
            fallback_skill_name="conversation-skill",
        )

        # 7. Voice pipeline.
        from voice.pipeline import VoicePipeline

        self.voice = VoicePipeline(self.config)
        await self.voice.initialize()

        self._started = True
        logger.info(
            "Platform started with %d skill(s).",
            len(self.registry.loaded_skill_names),
        )
        return True

    async def shutdown(self) -> None:
        """Unload all skills in reverse load order and flush memory."""
        if self.registry is not None:
            await self.registry.unload_all()
        if self.memory is not None:
            try:
                self.memory.save()
            except Exception:  # noqa: BLE001
                pass
        self._started = False
        logger.info("Platform shut down.")

    # ------------------------------------------------------------------
    # Core processing (Requirements 1.7, 1.8, 8.1, 8.7)
    # ------------------------------------------------------------------

    async def process_utterance(
        self,
        utterance: str,
        session_id: str = "default",
    ) -> PlatformResponse:
        """Process a user utterance end-to-end and return a response.

        Fetches context → routes the utterance → invokes the skill.  Skill
        exceptions are caught and converted into a safe error response
        (Requirement 8.1) while conversation state is preserved
        (Requirement 8.7).
        """
        if not self._started:
            return PlatformResponse(
                text="The platform is not ready yet. Please try again in a moment.",
                skill_name=None,
                confidence=0.0,
                metadata={},
                error="not_started",
            )

        utterance = (utterance or "").strip()
        if not utterance:
            return PlatformResponse(
                text="I didn't catch that. Could you say it again?",
                skill_name=None,
                confidence=0.0,
                metadata={},
            )

        start_time = time.monotonic()

        # 1. Record the user turn and fetch context.
        self.memory.add_turn("user", utterance)
        ctx = self.context.get_skill_context(session_id)

        # 2. Route the utterance.
        try:
            routing = await self.router.route(utterance, ctx)
        except Exception as exc:  # noqa: BLE001
            self.platform_logger.log_error("Intent routing failed", exc)
            return PlatformResponse(
                text="I'm having trouble understanding requests right now. "
                "Please try again.",
                skill_name=None,
                confidence=0.0,
                metadata={},
                error="routing_failed",
            )

        skill = routing.skill
        if skill is None:
            reply = "I'm not sure how to help with that yet."
            self.memory.add_turn("assistant", reply)
            self.memory.save()
            return PlatformResponse(
                text=reply,
                skill_name=None,
                confidence=routing.confidence,
                metadata={"fallback_used": routing.fallback_used},
            )

        skill_name = getattr(skill, "name", "unknown")

        # 3. Circuit-breaker check (Requirement 8.6).
        if self.error_handler.is_skill_disabled(skill_name):
            reply = (
                f"The {skill_name} feature is temporarily unavailable. "
                "Please try again in a few minutes."
            )
            self.memory.add_turn("assistant", reply, skill_name=skill_name)
            self.memory.save()
            return PlatformResponse(
                text=reply,
                skill_name=skill_name,
                confidence=routing.confidence,
                metadata={"disabled": True},
            )

        # 4. Build the skill context and execute.
        skill_context = SkillContext(
            utterance=utterance,
            intent_name=routing.intent_name,
            entities=routing.entities,
            conversation_history=ctx.get("conversation_history", []),
            user_preferences=ctx.get("user_preferences", {}),
            session_id=session_id,
        )

        try:
            response: SkillResponse = await skill.execute(skill_context)
            self.error_handler.reset_skill_errors(skill_name)
        except Exception as exc:  # noqa: BLE001
            # Catch skill errors, log, and return a safe message (Req 8.1, 8.7).
            platform_error = self.error_handler.handle_skill_error(skill_name, exc)
            safe_message = ErrorHandler.to_user_message(platform_error)
            # Conversation state is preserved — history/prefs untouched.
            self.memory.add_turn("assistant", safe_message, skill_name=skill_name)
            self.memory.save()
            return PlatformResponse(
                text=safe_message,
                skill_name=skill_name,
                confidence=routing.confidence,
                metadata={"error_category": platform_error.category.value},
                error=platform_error.category.value,
            )

        # 5. Record response, handle follow-ups, log timing.
        reply_text = response.text or ""
        self.memory.add_turn("assistant", reply_text, skill_name=skill_name)
        self.memory.save()

        if response.follow_up_prompt:
            self.context.add_follow_up(response.follow_up_prompt)
        self.context.set_active_skill(
            None if response.should_end_session else skill_name
        )

        elapsed_ms = (time.monotonic() - start_time) * 1000.0
        self.platform_logger.log_skill_invocation(skill_name, utterance, elapsed_ms)

        return PlatformResponse(
            text=reply_text,
            skill_name=skill_name,
            confidence=routing.confidence,
            metadata={
                "fallback_used": routing.fallback_used,
                "should_end_session": response.should_end_session,
                "follow_up_prompt": response.follow_up_prompt,
                **(response.metadata or {}),
            },
        )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_skill_registry(self):
        return self.registry

    def get_ai_provider(self):
        return self.ai_manager

    def get_voice_pipeline(self):
        return self.voice

    def get_config(self):
        return self.config

    @property
    def started(self) -> bool:
        return self._started

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_defaults(self) -> None:
        """Populate any missing top-level config keys with sensible defaults."""
        assert self.config is not None
        for key, value in _default_config().items():
            if self.config.get(key) is None:
                self.config.set(key, value)
        # Persist so subsequent runs / interfaces share the same config.
        self.config.save()

    def _resolve_log_level(self) -> int:
        level_name = str(
            (self.config.get("logging", {}) or {}).get("level", "INFO")
        ).upper()
        return getattr(logging, level_name, logging.INFO)
