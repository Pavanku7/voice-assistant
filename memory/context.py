"""
Context Manager for the Meryna Voice Platform.

Maintains ephemeral conversation state (active skill, follow-up queue,
session data) and assembles the context dict passed to each skill
execution.  All public methods are thread-safe via an internal lock.

Requirements covered:
    6.3 – Maintain current conversation state including active skill identifier
          and a queue of up to 5 pending follow-up prompts.
    6.4 – Provide the 10 most recent conversation turns and all stored user
          preferences when a skill requests context.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from meryna_platform.models import ConversationState
from memory.manager import MemoryManager

logger = logging.getLogger("meryna.context")


class ContextManager:
    """Maintains conversation state and provides context to skills.

    Parameters
    ----------
    memory_manager:
        The :class:`~memory.manager.MemoryManager` used to read conversation
        history and user preferences.

    Notes
    -----
    The internal :class:`~platform.models.ConversationState` is *ephemeral* —
    it is not persisted to disk and is reset whenever :meth:`clear_state` is
    called or the platform shuts down.
    """

    MAX_FOLLOW_UPS: int = 5
    CONTEXT_TURNS: int = 10

    def __init__(self, memory_manager: MemoryManager) -> None:
        self._memory = memory_manager
        self._state = ConversationState()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Context retrieval
    # ------------------------------------------------------------------

    def get_skill_context(self, session_id: str) -> Dict[str, Any]:
        """Return context for skill execution.

        Assembles the last :attr:`CONTEXT_TURNS` (10) conversation turns and
        all stored user preferences into a dict suitable for passing to a
        skill's ``execute()`` method.

        Parameters
        ----------
        session_id:
            The current session identifier (included in the returned dict for
            traceability).

        Returns
        -------
        Dict[str, Any]
            A dict with the following keys:

            * ``conversation_history``: list of dicts, each with keys
              ``role``, ``content``, ``timestamp``, and ``skill_name``.
              Ordered oldest-first, at most 10 entries.
            * ``user_preferences``: dict of all user preference fields.
            * ``session_id``: echoes the *session_id* parameter.
        """
        turns = self._memory.get_history(limit=self.CONTEXT_TURNS)
        conversation_history: List[Dict[str, Any]] = [
            asdict(turn) for turn in turns
        ]

        prefs = self._memory.get_preferences()
        user_preferences: Dict[str, Any] = asdict(prefs)

        return {
            "conversation_history": conversation_history,
            "user_preferences": user_preferences,
            "session_id": session_id,
        }

    # ------------------------------------------------------------------
    # Active skill
    # ------------------------------------------------------------------

    def set_active_skill(self, skill_name: Optional[str]) -> None:
        """Set the identifier of the currently active skill.

        Pass ``None`` to indicate no skill is active.

        Parameters
        ----------
        skill_name:
            Skill identifier string, or ``None``.
        """
        with self._lock:
            self._state.active_skill = skill_name

    def get_active_skill(self) -> Optional[str]:
        """Return the identifier of the currently active skill, or ``None``."""
        with self._lock:
            return self._state.active_skill

    # ------------------------------------------------------------------
    # Follow-up queue
    # ------------------------------------------------------------------

    def add_follow_up(self, prompt: str) -> bool:
        """Enqueue a follow-up prompt.

        The queue is capped at :attr:`MAX_FOLLOW_UPS` (5) items.

        Parameters
        ----------
        prompt:
            The follow-up prompt string to enqueue.

        Returns
        -------
        bool
            ``True`` if the prompt was added; ``False`` if the queue is
            already full (5 items).
        """
        with self._lock:
            if len(self._state.follow_up_queue) >= self.MAX_FOLLOW_UPS:
                logger.debug(
                    "ContextManager: follow-up queue is full (max %d); "
                    "prompt rejected: %r",
                    self.MAX_FOLLOW_UPS,
                    prompt,
                )
                return False
            self._state.follow_up_queue.append(prompt)
            return True

    def pop_follow_up(self) -> Optional[str]:
        """Remove and return the next follow-up prompt from the queue.

        Returns
        -------
        Optional[str]
            The oldest follow-up prompt, or ``None`` if the queue is empty.
        """
        with self._lock:
            if not self._state.follow_up_queue:
                return None
            return self._state.follow_up_queue.pop(0)

    # ------------------------------------------------------------------
    # Session data
    # ------------------------------------------------------------------

    def set_session_data(self, key: str, value: Any) -> None:
        """Store a session-scoped key/value pair.

        Session data is ephemeral — it does not survive a :meth:`clear_state`
        call or platform shutdown.

        Parameters
        ----------
        key:
            Arbitrary string key.
        value:
            Any JSON-serialisable value.
        """
        with self._lock:
            self._state.session_data[key] = value

    def get_session_data(self, key: str) -> Optional[Any]:
        """Retrieve a session-scoped value by key.

        Parameters
        ----------
        key:
            The key to look up.

        Returns
        -------
        Optional[Any]
            The stored value, or ``None`` if the key does not exist.
        """
        with self._lock:
            return self._state.session_data.get(key)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def clear_state(self) -> None:
        """Reset all ephemeral conversation state.

        Clears the active skill identifier, empties the follow-up queue, and
        removes all session data.  Does *not* affect persisted conversation
        history or user preferences managed by :class:`~memory.manager.MemoryManager`.
        """
        with self._lock:
            self._state = ConversationState()
