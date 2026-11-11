"""
Memory Manager for the Meryna Voice Platform.

Persists conversation history and user preferences to a JSON file in the
user's home directory (or a configurable path).  All public methods are
thread-safe via an internal ``threading.Lock``.

Requirements covered:
    6.1 – Persist conversation history to a configurable storage location;
          default: user's home directory.
    6.2 – Load previous conversation history at startup up to the
          configurable history limit (default 30 turns).
    6.5 – User preference storage with field validation.
    6.6 – In-memory fallback when the storage location is unavailable.
    6.7 – Discard corrupted/invalid data and start with empty history.
    6.8 – Retain data in memory on write failure; retry on next save.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from meryna_platform.models import ConversationTurn, UserPreferences

logger = logging.getLogger("meryna.memory")


class MemoryManager:
    """Persists conversation history and user preferences.

    Parameters
    ----------
    storage_path:
        Full path to the JSON memory file.  Defaults to
        ``~/.meryna_memory.json`` when *None*.
    history_limit:
        Maximum number of conversation turns to keep in memory and on disk.
        Defaults to 30.
    """

    MEMORY_FILE = ".meryna_memory.json"
    DEFAULT_HISTORY_LIMIT = 30

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self._storage_path: Path = (
            storage_path if storage_path is not None
            else Path.home() / self.MEMORY_FILE
        )
        self._history_limit: int = history_limit

        self._history: List[ConversationTurn] = []
        self._preferences: UserPreferences = UserPreferences()
        self._in_memory_only: bool = False

        # Tracks whether there is unsaved data that should be retried
        # on the next call to save() (Requirement 6.8).
        self._pending_write: bool = False

        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Load history and preferences from the storage file.

        Behaviour
        ---------
        * If the storage path is unavailable (parent directory missing /
          unwritable / unreadable), switches to in-memory-only mode and
          logs a warning (Requirement 6.6).
        * If the file does not exist, starts with empty history (clean
          first-run state) — not treated as an error.
        * If the file contains corrupted or invalid data, discards it,
          starts with empty history, and logs a warning (Requirement 6.7).

        Returns
        -------
        bool
            ``True`` if data was loaded successfully (or the file simply
            didn't exist yet), ``False`` if storage is completely
            unavailable.
        """
        with self._lock:
            # Check whether the storage location is accessible.
            storage_dir = self._storage_path.parent
            try:
                storage_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning(
                    "MemoryManager: storage path %s is unavailable (%s). "
                    "Operating in in-memory-only mode.",
                    self._storage_path,
                    exc,
                )
                self._in_memory_only = True
                return False

            # If the file doesn't exist yet, that's fine — clean start.
            if not self._storage_path.exists():
                return True

            # Attempt to read and parse the file.
            try:
                raw = self._storage_path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except OSError as exc:
                logger.warning(
                    "MemoryManager: cannot read %s (%s). "
                    "Operating in in-memory-only mode.",
                    self._storage_path,
                    exc,
                )
                self._in_memory_only = True
                return False
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning(
                    "MemoryManager: corrupted memory file %s (%s). "
                    "Starting with empty history.",
                    self._storage_path,
                    exc,
                )
                self._history = []
                self._preferences = UserPreferences()
                return True

            # Validate top-level structure.
            if not isinstance(data, dict):
                logger.warning(
                    "MemoryManager: memory file %s has unexpected format "
                    "(expected a JSON object). Starting with empty history.",
                    self._storage_path,
                )
                self._history = []
                self._preferences = UserPreferences()
                return True

            # Deserialise history.
            try:
                raw_history = data.get("history", [])
                if not isinstance(raw_history, list):
                    raise ValueError("'history' must be a JSON array")

                history: List[ConversationTurn] = []
                for item in raw_history:
                    if not isinstance(item, dict):
                        raise ValueError(
                            f"Each history turn must be a JSON object, got {type(item).__name__}"
                        )
                    history.append(
                        ConversationTurn(
                            role=str(item["role"]),
                            content=str(item["content"]),
                            timestamp=float(item["timestamp"]),
                            skill_name=item.get("skill_name"),
                        )
                    )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "MemoryManager: corrupted history in %s (%s). "
                    "Starting with empty history.",
                    self._storage_path,
                    exc,
                )
                self._history = []
                self._preferences = UserPreferences()
                return True

            # Deserialise preferences (lenient — fall back to defaults).
            prefs_data = data.get("preferences", {})
            if not isinstance(prefs_data, dict):
                prefs_data = {}
            preferences = self._deserialise_preferences(prefs_data)

            # Apply history limit.
            if len(history) > self._history_limit:
                history = history[-self._history_limit :]

            self._history = history
            self._preferences = preferences
            return True

    def save(self) -> bool:
        """Persist current history and preferences to the storage file.

        Behaviour
        ---------
        * If the manager is in in-memory-only mode, returns ``False``
          immediately — there is no storage to write to.
        * If the write fails, retains all data in memory, marks a pending
          write, logs a warning, and returns ``False`` (Requirement 6.8).
        * On the next call to ``save()``, a pending write is retried
          regardless of whether new data was added.

        Returns
        -------
        bool
            ``True`` if the data was successfully written to disk.
        """
        with self._lock:
            if self._in_memory_only:
                return False

            payload = {
                "history": [asdict(turn) for turn in self._history],
                "preferences": asdict(self._preferences),
            }

            try:
                # Atomic(-ish) write: write to a temp file then rename.
                tmp_path = self._storage_path.with_suffix(".tmp")
                tmp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp_path.replace(self._storage_path)
                self._pending_write = False
                return True
            except OSError as exc:
                logger.warning(
                    "MemoryManager: failed to write %s (%s). "
                    "Data retained in memory; will retry on next save.",
                    self._storage_path,
                    exc,
                )
                self._pending_write = True
                return False

    # ------------------------------------------------------------------
    # Conversation history
    # ------------------------------------------------------------------

    def add_turn(
        self,
        role: str,
        content: str,
        skill_name: Optional[str] = None,
    ) -> None:
        """Append a conversation turn to the in-memory history.

        Enforces the history limit by discarding the oldest turn when the
        limit is exceeded.

        Parameters
        ----------
        role:
            ``"user"`` or ``"assistant"``.
        content:
            The spoken/written text of the turn.
        skill_name:
            Optional name of the skill that produced the response.
        """
        turn = ConversationTurn(
            role=role,
            content=content,
            timestamp=time.time(),
            skill_name=skill_name,
        )
        with self._lock:
            self._history.append(turn)
            if len(self._history) > self._history_limit:
                # Keep only the most recent turns.
                self._history = self._history[-self._history_limit :]

    def get_history(self, limit: Optional[int] = None) -> List[ConversationTurn]:
        """Return a copy of the conversation history.

        Parameters
        ----------
        limit:
            If provided, return at most the most recent *limit* turns.
            Must be a positive integer or ``None``.

        Returns
        -------
        List[ConversationTurn]
            Ordered oldest-first.
        """
        with self._lock:
            if limit is not None and limit > 0:
                return list(self._history[-limit:])
            return list(self._history)

    def clear_history(self) -> None:
        """Remove all conversation turns from memory."""
        with self._lock:
            self._history = []

    # ------------------------------------------------------------------
    # User preferences
    # ------------------------------------------------------------------

    def get_preferences(self) -> UserPreferences:
        """Return a copy of the current user preferences."""
        with self._lock:
            # Return a shallow copy so callers cannot mutate internal state.
            prefs = self._preferences
            return UserPreferences(
                name=prefs.name,
                location=prefs.location,
                voice_id=prefs.voice_id,
                speech_rate=prefs.speech_rate,
                volume=prefs.volume,
            )

    def set_preferences(self, preferences: UserPreferences) -> bool:
        """Validate and store new user preferences.

        Validation rules (Requirement 6.5):
        * ``name``        — at most 50 characters.
        * ``location``    — at most 100 characters.
        * ``speech_rate`` — integer in the range 50–300 (inclusive).
        * ``volume``      — float in the range 0.0–1.0 (inclusive).

        Parameters
        ----------
        preferences:
            A :class:`~platform.models.UserPreferences` instance.

        Returns
        -------
        bool
            ``True`` if preferences were accepted and stored; ``False``
            if any field failed validation (existing preferences retained).
        """
        errors = self._validate_preferences(preferences)
        if errors:
            for msg in errors:
                logger.warning("MemoryManager: preference validation failed — %s", msg)
            return False

        with self._lock:
            self._preferences = preferences
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_preferences(prefs: UserPreferences) -> List[str]:
        """Return a list of validation error messages (empty = valid)."""
        errors: List[str] = []

        if len(prefs.name) > 50:
            errors.append(
                f"name must be at most 50 characters (got {len(prefs.name)})"
            )
        if len(prefs.location) > 100:
            errors.append(
                f"location must be at most 100 characters (got {len(prefs.location)})"
            )
        if not (50 <= prefs.speech_rate <= 300):
            errors.append(
                f"speech_rate must be between 50 and 300 (got {prefs.speech_rate})"
            )
        if not (0.0 <= prefs.volume <= 1.0):
            errors.append(
                f"volume must be between 0.0 and 1.0 (got {prefs.volume})"
            )
        return errors

    @staticmethod
    def _deserialise_preferences(data: dict) -> UserPreferences:
        """Build a :class:`UserPreferences` from a raw dict, using field defaults
        for any missing or invalid values."""
        defaults = UserPreferences()

        def _str(key: str, default: str, max_len: int) -> str:
            val = data.get(key, default)
            if not isinstance(val, str):
                return default
            return val[:max_len]  # Silently truncate overly long values.

        def _int_range(key: str, default: int, lo: int, hi: int) -> int:
            val = data.get(key, default)
            try:
                val = int(val)
            except (TypeError, ValueError):
                return default
            return max(lo, min(hi, val))

        def _float_range(key: str, default: float, lo: float, hi: float) -> float:
            val = data.get(key, default)
            try:
                val = float(val)
            except (TypeError, ValueError):
                return default
            return max(lo, min(hi, val))

        voice_id = data.get("voice_id")
        if voice_id is not None and not isinstance(voice_id, str):
            voice_id = None

        return UserPreferences(
            name=_str("name", defaults.name, 50),
            location=_str("location", defaults.location, 100),
            voice_id=voice_id,
            speech_rate=_int_range("speech_rate", defaults.speech_rate, 50, 300),
            volume=_float_range("volume", defaults.volume, 0.0, 1.0),
        )

    # ------------------------------------------------------------------
    # Properties (read-only)
    # ------------------------------------------------------------------

    @property
    def in_memory_only(self) -> bool:
        """``True`` when the manager has fallen back to in-memory storage."""
        return self._in_memory_only

    @property
    def has_pending_write(self) -> bool:
        """``True`` when a previous :meth:`save` failed and a retry is due."""
        return self._pending_write

    @property
    def storage_path(self) -> Path:
        """The resolved path to the memory file."""
        return self._storage_path
