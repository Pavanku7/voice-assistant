"""
Error handling, circuit breaker, and retry logic for the Meryna Voice Platform.

This module provides:
- ``ErrorHandler``: centralised error handling with circuit-breaker and retry.
- ``is_retryable_error``: convenience helper used by callers to build predicates.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from meryna_platform.models import ErrorCategory, PlatformError

if TYPE_CHECKING:
    # Avoid circular / missing-module import at runtime; PlatformLogger is only
    # needed for type annotations here.
    from meryna_platform.logging import PlatformLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_retryable_error(exc: Exception) -> bool:
    """
    Return *True* when *exc* represents a transient failure that is worth
    retrying: network timeouts, connection resets, and HTTP 5xx responses.

    Callers may pass this directly as the ``is_retryable`` argument to
    :py:meth:`ErrorHandler.with_retry`.
    """
    import socket

    # Network-level errors
    transient_types = (
        TimeoutError,
        ConnectionResetError,
        ConnectionRefusedError,
        ConnectionAbortedError,
        socket.timeout,
        OSError,  # covers many lower-level network errors on Windows/Linux
    )
    if isinstance(exc, transient_types):
        return True

    # HTTP 5xx – several common HTTP libraries surface status codes as attrs
    for attr in ("status_code", "status", "code", "response"):
        value = getattr(exc, attr, None)
        if value is None:
            continue
        # Some libraries attach the response object; drill one level deeper
        if hasattr(value, "status_code"):
            value = value.status_code
        try:
            if 500 <= int(value) <= 599:
                return True
        except (TypeError, ValueError):
            pass

    # asyncio timeouts
    if isinstance(exc, asyncio.TimeoutError):
        return True

    return False


# ---------------------------------------------------------------------------
# ErrorHandler
# ---------------------------------------------------------------------------


class ErrorHandler:
    """
    Centralised error handling with circuit-breaker and exponential-backoff
    retry logic.

    Circuit-breaker parameters
    --------------------------
    After ``CIRCUIT_BREAKER_THRESHOLD`` consecutive errors inside a
    ``CIRCUIT_BREAKER_WINDOW``-second window the skill is disabled for
    ``CIRCUIT_BREAKER_TIMEOUT`` seconds.

    Retry parameters
    ----------------
    :py:meth:`with_retry` performs up to ``MAX_RETRIES`` attempts with
    delays that grow as ``INITIAL_DELAY * 2^attempt``, capped at
    ``MAX_DELAY``.
    """

    MAX_RETRIES: int = 3
    INITIAL_DELAY: float = 1.0
    MAX_DELAY: float = 30.0
    CIRCUIT_BREAKER_THRESHOLD: int = 3
    CIRCUIT_BREAKER_WINDOW: float = 300.0  # seconds (5 minutes)
    CIRCUIT_BREAKER_TIMEOUT: float = 300.0  # seconds (5 minutes)

    def __init__(self, logger: "PlatformLogger") -> None:
        """
        Initialise the handler.

        Parameters
        ----------
        logger:
            A :class:`~platform.logging.PlatformLogger` instance used to
            record errors and circuit-breaker events internally.
        """
        self._logger = logger
        # skill_name -> list of UTC epoch timestamps of recent errors
        self._skill_errors: Dict[str, List[float]] = {}
        # skill_name -> UTC epoch timestamp when the skill was disabled
        self._disabled_skills: Dict[str, float] = {}

        # Fall back to stdlib logger when PlatformLogger is unavailable
        self._fallback_log: logging.Logger = logging.getLogger(
            "meryna.error_handler"
        )

    # ------------------------------------------------------------------
    # Skill error handling / circuit breaker
    # ------------------------------------------------------------------

    def handle_skill_error(
        self,
        skill_name: str,
        exception: Exception,
    ) -> PlatformError:
        """
        Record a skill execution error and apply circuit-breaker logic.

        If ``CIRCUIT_BREAKER_THRESHOLD`` errors are recorded within
        ``CIRCUIT_BREAKER_WINDOW`` seconds the skill is disabled for
        ``CIRCUIT_BREAKER_TIMEOUT`` seconds.

        Parameters
        ----------
        skill_name:
            The name of the skill that raised the exception.
        exception:
            The exception that was raised during skill execution.

        Returns
        -------
        PlatformError
            A :class:`~platform.models.PlatformError` with a safe
            ``user_message`` and full ``internal_message`` for logging.
        """
        now = time.monotonic()

        # Purge timestamps outside the circuit-breaker window
        recent = self._skill_errors.get(skill_name, [])
        recent = [t for t in recent if now - t <= self.CIRCUIT_BREAKER_WINDOW]
        recent.append(now)
        self._skill_errors[skill_name] = recent

        internal_msg = (
            f"Skill '{skill_name}' raised {type(exception).__name__}: {exception}"
        )
        self._log_error(internal_msg, exception, skill_name)

        # Check circuit-breaker threshold
        if len(recent) >= self.CIRCUIT_BREAKER_THRESHOLD:
            self._disabled_skills[skill_name] = now
            disable_msg = (
                f"Circuit breaker tripped for skill '{skill_name}' after "
                f"{len(recent)} errors; disabled for "
                f"{int(self.CIRCUIT_BREAKER_TIMEOUT // 60)} minutes."
            )
            self._log_error(disable_msg, skill_name=skill_name)
            user_message = (
                f"The '{skill_name}' skill is temporarily unavailable. "
                "Please try again in a few minutes."
            )
        else:
            user_message = (
                f"The '{skill_name}' skill encountered a problem. "
                "Please try again."
            )

        return PlatformError(
            category=ErrorCategory.SKILL_ERROR,
            user_message=user_message,
            internal_message=internal_msg,
            service_name=skill_name,
            retryable=False,
        )

    def is_skill_disabled(self, skill_name: str) -> bool:
        """
        Return *True* if the skill is currently in the circuit-breaker
        disabled state.

        The disabled state expires automatically after
        ``CIRCUIT_BREAKER_TIMEOUT`` seconds; this method clears the entry
        once the timeout has passed.
        """
        disabled_at = self._disabled_skills.get(skill_name)
        if disabled_at is None:
            return False

        elapsed = time.monotonic() - disabled_at
        if elapsed >= self.CIRCUIT_BREAKER_TIMEOUT:
            # Timeout expired – remove the disabled state and reset error log
            del self._disabled_skills[skill_name]
            self._skill_errors.pop(skill_name, None)
            return False

        return True

    def reset_skill_errors(self, skill_name: str) -> None:
        """
        Clear the error history for *skill_name*.

        Call this after a successful skill execution so that sporadic single
        failures do not accumulate toward the circuit-breaker threshold.
        """
        self._skill_errors.pop(skill_name, None)
        self._disabled_skills.pop(skill_name, None)

    # ------------------------------------------------------------------
    # AI error handling
    # ------------------------------------------------------------------

    def handle_ai_error(self, exception: Exception) -> PlatformError:
        """
        Translate an AI-provider exception into a :class:`~platform.models.PlatformError`.

        Provides user-safe messages for the three most common failure modes:

        * **Rate limit** – HTTP 429 or ``RateLimitError`` in the exception
          class name or message.
        * **Authentication failure** – HTTP 401/403 or ``AuthenticationError``
          / ``PermissionError`` in the exception class name or message.
        * **Network error** – everything else (timeouts, connection resets,
          5xx responses).

        Parameters
        ----------
        exception:
            The exception raised by the AI provider.

        Returns
        -------
        PlatformError
            Safe error representation; ``internal_message`` contains full
            details for logging, ``user_message`` never exposes credentials
            or internals.
        """
        exc_type = type(exception).__name__
        exc_str = str(exception).lower()
        internal_msg = f"AI provider error ({exc_type}): {exception}"
        self._log_error(internal_msg, exception)

        # Determine status code if available
        status_code: Optional[int] = None
        for attr in ("status_code", "status", "code"):
            val = getattr(exception, attr, None)
            if val is not None:
                try:
                    status_code = int(val)
                    break
                except (TypeError, ValueError):
                    pass

        # --- Rate limit ---
        if (
            status_code == 429
            or "rate" in exc_str
            or "ratelimit" in exc_type.lower()
            or "quota" in exc_str
        ):
            return PlatformError(
                category=ErrorCategory.AI_RATE_LIMIT,
                user_message=(
                    "The AI service is temporarily busy. "
                    "Please wait at least 30 seconds before trying again."
                ),
                internal_message=internal_msg,
                retryable=True,
            )

        # --- Authentication / authorisation ---
        if (
            status_code in (401, 403)
            or "auth" in exc_str
            or "authentication" in exc_type.lower()
            or "permission" in exc_type.lower()
            or "unauthorized" in exc_str
            or "forbidden" in exc_str
            or "invalid_api_key" in exc_str
        ):
            return PlatformError(
                category=ErrorCategory.AI_AUTH_ERROR,
                user_message=(
                    "There is a configuration issue with the AI service. "
                    "Please check the AI service settings."
                ),
                internal_message=internal_msg,
                retryable=False,
            )

        # --- Network / transient error (catch-all) ---
        return PlatformError(
            category=ErrorCategory.NETWORK_ERROR,
            user_message=(
                "I'm having trouble reaching the AI service right now. "
                "Please check your internet connection and try again."
            ),
            internal_message=internal_msg,
            retryable=True,
        )

    # ------------------------------------------------------------------
    # Retry with exponential backoff
    # ------------------------------------------------------------------

    async def with_retry(
        self,
        operation: Callable[[], Any],
        is_retryable: Callable[[Exception], bool],
    ) -> Any:
        """
        Execute *operation* with exponential-backoff retry.

        The delay between attempts follows::

            delay = min(INITIAL_DELAY * 2 ** attempt, MAX_DELAY)

        where *attempt* starts at 0.  Up to ``MAX_RETRIES`` additional
        attempts are made (so the operation is called at most
        ``MAX_RETRIES + 1`` times total).

        Parameters
        ----------
        operation:
            A zero-argument callable (sync or async) to execute.
        is_retryable:
            A predicate that, given the raised exception, returns *True* if
            another attempt should be made.  Use
            :py:func:`is_retryable_error` as a sensible default.

        Returns
        -------
        Any
            The return value of *operation* on success.

        Raises
        ------
        Exception
            The last exception raised by *operation* if all attempts fail or
            the exception is not retryable.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(self.MAX_RETRIES + 1):  # 0, 1, 2, 3
            try:
                if inspect.iscoroutinefunction(operation):
                    return await operation()
                return operation()

            except Exception as exc:  # noqa: BLE001
                last_exc = exc

                if attempt == self.MAX_RETRIES or not is_retryable(exc):
                    # No more retries or not worth retrying
                    raise

                delay = min(
                    self.INITIAL_DELAY * (2 ** attempt),
                    self.MAX_DELAY,
                )
                self._log_error(
                    f"Attempt {attempt + 1}/{self.MAX_RETRIES} failed "
                    f"({type(exc).__name__}); retrying in {delay:.1f}s."
                )
                await asyncio.sleep(delay)

        # Should be unreachable, but satisfies type checkers
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # User-facing message formatter
    # ------------------------------------------------------------------

    @staticmethod
    def to_user_message(error: PlatformError) -> str:
        """
        Return the safe, user-facing message from *error*.

        This method **never** exposes stack traces, file paths, internal
        function names, or API credentials — it returns only the
        pre-validated :attr:`~platform.models.PlatformError.user_message`
        field.

        Parameters
        ----------
        error:
            A :class:`~platform.models.PlatformError` instance.

        Returns
        -------
        str
            A user-friendly string safe for display in any interface.
        """
        return error.user_message

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log_error(
        self,
        message: str,
        exception: Optional[Exception] = None,
        skill_name: Optional[str] = None,
    ) -> None:
        """Delegate to PlatformLogger if available, otherwise use stdlib."""
        try:
            # PlatformLogger.log_error signature: (message, exception, skill_name)
            self._logger.log_error(message, exception, skill_name)
        except Exception:  # noqa: BLE001
            # PlatformLogger not yet implemented or unavailable
            if exception is not None:
                self._fallback_log.error(message, exc_info=exception)
            else:
                self._fallback_log.error(message)
