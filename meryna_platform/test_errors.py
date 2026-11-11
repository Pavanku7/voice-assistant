"""
Unit tests for platform/errors.py.

Tests cover:
- Circuit breaker: disabling a skill after 3 errors within the 5-minute window
- Exponential backoff: delay sequence and cap at 30 s
- to_user_message(): never leaks internal details (stack traces, paths, etc.)
- handle_ai_error(): correct categories for rate-limit, auth, and network errors
- is_skill_disabled() / reset_skill_errors() lifecycle
"""

from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from meryna_platform.errors import ErrorHandler, is_retryable_error
from meryna_platform.models import ErrorCategory, PlatformError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler() -> ErrorHandler:
    """Return an ErrorHandler with a mock PlatformLogger."""
    mock_logger = MagicMock()
    mock_logger.log_error = MagicMock()
    return ErrorHandler(mock_logger)


# ---------------------------------------------------------------------------
# Circuit-breaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker(unittest.TestCase):
    """Tests for handle_skill_error() and is_skill_disabled()."""

    def test_single_error_does_not_disable_skill(self) -> None:
        handler = _make_handler()
        handler.handle_skill_error("my_skill", ValueError("oops"))
        self.assertFalse(handler.is_skill_disabled("my_skill"))

    def test_two_errors_do_not_disable_skill(self) -> None:
        handler = _make_handler()
        for _ in range(2):
            handler.handle_skill_error("my_skill", ValueError("oops"))
        self.assertFalse(handler.is_skill_disabled("my_skill"))

    def test_three_errors_disable_skill(self) -> None:
        handler = _make_handler()
        for _ in range(3):
            result = handler.handle_skill_error("my_skill", ValueError("oops"))
        self.assertTrue(handler.is_skill_disabled("my_skill"))
        # The returned error should mention unavailability
        self.assertIn("temporarily unavailable", result.user_message.lower())

    def test_circuit_breaker_only_counts_errors_within_window(self) -> None:
        """Errors outside the 5-minute window should not contribute."""
        handler = _make_handler()
        skill = "old_skill"
        # Plant two "old" timestamps well outside the window
        now = time.monotonic()
        handler._skill_errors[skill] = [
            now - handler.CIRCUIT_BREAKER_WINDOW - 60,
            now - handler.CIRCUIT_BREAKER_WINDOW - 30,
        ]
        # A single new error should NOT trip the breaker
        handler.handle_skill_error(skill, RuntimeError("fresh"))
        self.assertFalse(handler.is_skill_disabled(skill))

    def test_disabled_skill_recovers_after_timeout(self) -> None:
        """is_skill_disabled() should return False once the timeout expires."""
        handler = _make_handler()
        # Manually plant a disable timestamp in the past beyond the timeout
        handler._disabled_skills["skill_x"] = (
            time.monotonic() - handler.CIRCUIT_BREAKER_TIMEOUT - 1
        )
        self.assertFalse(handler.is_skill_disabled("skill_x"))
        # The entry should have been cleaned up
        self.assertNotIn("skill_x", handler._disabled_skills)

    def test_reset_skill_errors_clears_state(self) -> None:
        handler = _make_handler()
        for _ in range(3):
            handler.handle_skill_error("skill_y", IOError("fail"))
        self.assertTrue(handler.is_skill_disabled("skill_y"))
        handler.reset_skill_errors("skill_y")
        self.assertFalse(handler.is_skill_disabled("skill_y"))

    def test_unknown_skill_is_not_disabled(self) -> None:
        handler = _make_handler()
        self.assertFalse(handler.is_skill_disabled("nonexistent_skill"))

    def test_errors_on_different_skills_are_independent(self) -> None:
        handler = _make_handler()
        for _ in range(3):
            handler.handle_skill_error("bad_skill", RuntimeError("x"))
        # Different skill should NOT be disabled
        self.assertTrue(handler.is_skill_disabled("bad_skill"))
        self.assertFalse(handler.is_skill_disabled("good_skill"))

    def test_error_result_category(self) -> None:
        handler = _make_handler()
        result = handler.handle_skill_error("s", Exception("boom"))
        self.assertEqual(result.category, ErrorCategory.SKILL_ERROR)

    def test_error_result_has_service_name(self) -> None:
        handler = _make_handler()
        result = handler.handle_skill_error("my_skill", Exception("boom"))
        self.assertEqual(result.service_name, "my_skill")


# ---------------------------------------------------------------------------
# Exponential backoff / with_retry tests
# ---------------------------------------------------------------------------


class TestWithRetry(unittest.IsolatedAsyncioTestCase):
    """Tests for with_retry() exponential backoff behaviour."""

    async def test_success_on_first_attempt(self) -> None:
        handler = _make_handler()
        call_count = 0

        async def op() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await handler.with_retry(op, lambda e: True)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count, 1)

    async def test_success_after_transient_failure(self) -> None:
        handler = _make_handler()
        attempts = []

        async def op() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise TimeoutError("transient")
            return "success"

        with patch("asyncio.sleep", return_value=None) as mock_sleep:
            result = await handler.with_retry(op, lambda e: True)

        self.assertEqual(result, "success")
        self.assertEqual(len(attempts), 3)
        # Two sleeps should have occurred between attempts
        self.assertEqual(mock_sleep.call_count, 2)

    async def test_delays_follow_exponential_backoff(self) -> None:
        """Delays should be 1 s, 2 s (capped at 30 s)."""
        handler = _make_handler()
        recorded_delays: list[float] = []

        async def op() -> None:
            raise TimeoutError("always fails")

        async def fake_sleep(delay: float) -> None:
            recorded_delays.append(delay)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            with self.assertRaises(TimeoutError):
                await handler.with_retry(op, lambda e: True)

        # Expected delays: 1.0, 2.0, 4.0  (3 retries → 3 sleeps)
        self.assertEqual(len(recorded_delays), handler.MAX_RETRIES)
        self.assertAlmostEqual(recorded_delays[0], 1.0)
        self.assertAlmostEqual(recorded_delays[1], 2.0)
        self.assertAlmostEqual(recorded_delays[2], 4.0)

    async def test_delay_capped_at_max_delay(self) -> None:
        """Delay should never exceed MAX_DELAY (30 s)."""
        handler = _make_handler()
        # Override to force high initial delay
        handler.INITIAL_DELAY = 20.0
        recorded_delays: list[float] = []

        async def op() -> None:
            raise TimeoutError("fail")

        async def fake_sleep(delay: float) -> None:
            recorded_delays.append(delay)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            with self.assertRaises(TimeoutError):
                await handler.with_retry(op, lambda e: True)

        for d in recorded_delays:
            self.assertLessEqual(d, handler.MAX_DELAY)

    async def test_non_retryable_error_raises_immediately(self) -> None:
        handler = _make_handler()
        call_count = 0

        async def op() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with patch("asyncio.sleep", return_value=None) as mock_sleep:
            with self.assertRaises(ValueError):
                await handler.with_retry(op, lambda e: False)

        self.assertEqual(call_count, 1)
        mock_sleep.assert_not_called()

    async def test_max_retries_exhausted_raises_last_exception(self) -> None:
        handler = _make_handler()

        async def op() -> None:
            raise ConnectionResetError("reset")

        with patch("asyncio.sleep", return_value=None):
            with self.assertRaises(ConnectionResetError):
                await handler.with_retry(op, lambda e: True)

    async def test_sync_operation_is_supported(self) -> None:
        """with_retry should also work with plain (non-async) callables."""
        handler = _make_handler()

        def sync_op() -> int:
            return 42

        result = await handler.with_retry(sync_op, lambda e: False)
        self.assertEqual(result, 42)


# ---------------------------------------------------------------------------
# to_user_message() — information-safety tests
# ---------------------------------------------------------------------------


class TestToUserMessage(unittest.TestCase):
    """Tests that to_user_message() never leaks internal details."""

    def _make_error(
        self,
        user_message: str,
        internal_message: str,
        category: ErrorCategory = ErrorCategory.SKILL_ERROR,
    ) -> PlatformError:
        return PlatformError(
            category=category,
            user_message=user_message,
            internal_message=internal_message,
        )

    def test_returns_user_message_exactly(self) -> None:
        err = self._make_error("Something went wrong.", "Traceback (most recent call last)...")
        self.assertEqual(ErrorHandler.to_user_message(err), "Something went wrong.")

    def test_does_not_contain_stack_trace(self) -> None:
        internal = "Traceback (most recent call last):\n  File '/app/platform/core.py', line 42\nValueError: bad"
        err = self._make_error("Oops.", internal)
        msg = ErrorHandler.to_user_message(err)
        self.assertNotIn("Traceback", msg)
        self.assertNotIn("platform/core.py", msg)
        self.assertNotIn("ValueError", msg)

    def test_does_not_contain_file_path(self) -> None:
        internal = "Error in /home/user/.venv/lib/python3.11/site-packages/requests/__init__.py"
        err = self._make_error("Service error.", internal)
        msg = ErrorHandler.to_user_message(err)
        self.assertNotIn("/home/", msg)
        self.assertNotIn("site-packages", msg)

    def test_does_not_contain_api_credentials(self) -> None:
        internal = "401 Unauthorized: API key sk-abc123secret is invalid"
        err = self._make_error("Config issue.", internal)
        msg = ErrorHandler.to_user_message(err)
        self.assertNotIn("sk-abc123secret", msg)
        self.assertNotIn("API key", msg)

    def test_does_not_contain_function_name(self) -> None:
        internal = "Exception in _internal_helper() at core.py:88"
        err = self._make_error("Something failed.", internal)
        msg = ErrorHandler.to_user_message(err)
        self.assertNotIn("_internal_helper", msg)

    def test_empty_user_message_is_returned_as_is(self) -> None:
        err = self._make_error("", "secret internal detail")
        self.assertEqual(ErrorHandler.to_user_message(err), "")


# ---------------------------------------------------------------------------
# handle_ai_error() tests
# ---------------------------------------------------------------------------


class TestHandleAiError(unittest.TestCase):
    """Tests for correct error category assignment in handle_ai_error()."""

    def setUp(self) -> None:
        self.handler = _make_handler()

    def _exc_with_status(self, status: int, msg: str = "") -> Exception:
        exc = Exception(msg)
        exc.status_code = status  # type: ignore[attr-defined]
        return exc

    def test_rate_limit_by_status_429(self) -> None:
        exc = self._exc_with_status(429, "Too Many Requests")
        result = self.handler.handle_ai_error(exc)
        self.assertEqual(result.category, ErrorCategory.AI_RATE_LIMIT)
        self.assertIn("30 seconds", result.user_message)

    def test_rate_limit_by_message_keyword(self) -> None:
        exc = Exception("rate limit exceeded")
        result = self.handler.handle_ai_error(exc)
        self.assertEqual(result.category, ErrorCategory.AI_RATE_LIMIT)

    def test_rate_limit_by_quota_keyword(self) -> None:
        exc = Exception("quota exhausted for today")
        result = self.handler.handle_ai_error(exc)
        self.assertEqual(result.category, ErrorCategory.AI_RATE_LIMIT)

    def test_auth_error_by_status_401(self) -> None:
        exc = self._exc_with_status(401, "Unauthorized")
        result = self.handler.handle_ai_error(exc)
        self.assertEqual(result.category, ErrorCategory.AI_AUTH_ERROR)

    def test_auth_error_by_status_403(self) -> None:
        exc = self._exc_with_status(403, "Forbidden")
        result = self.handler.handle_ai_error(exc)
        self.assertEqual(result.category, ErrorCategory.AI_AUTH_ERROR)

    def test_auth_error_by_message_keyword(self) -> None:
        exc = Exception("authentication failed: invalid_api_key")
        result = self.handler.handle_ai_error(exc)
        self.assertEqual(result.category, ErrorCategory.AI_AUTH_ERROR)

    def test_network_error_for_timeout(self) -> None:
        exc = TimeoutError("connection timed out")
        result = self.handler.handle_ai_error(exc)
        self.assertEqual(result.category, ErrorCategory.NETWORK_ERROR)

    def test_network_error_for_connection_reset(self) -> None:
        exc = ConnectionResetError("connection reset by peer")
        result = self.handler.handle_ai_error(exc)
        self.assertEqual(result.category, ErrorCategory.NETWORK_ERROR)

    def test_retryable_flag_on_rate_limit(self) -> None:
        exc = self._exc_with_status(429)
        result = self.handler.handle_ai_error(exc)
        self.assertTrue(result.retryable)

    def test_not_retryable_on_auth_error(self) -> None:
        exc = self._exc_with_status(401)
        result = self.handler.handle_ai_error(exc)
        self.assertFalse(result.retryable)

    def test_internal_message_not_in_user_message(self) -> None:
        exc = self._exc_with_status(429, "secret_key=abc123")
        result = self.handler.handle_ai_error(exc)
        self.assertNotIn("secret_key", result.user_message)
        self.assertNotIn("abc123", result.user_message)


# ---------------------------------------------------------------------------
# is_retryable_error() helper tests
# ---------------------------------------------------------------------------


class TestIsRetryableError(unittest.TestCase):
    """Tests for the standalone is_retryable_error() helper."""

    def test_timeout_error_is_retryable(self) -> None:
        self.assertTrue(is_retryable_error(TimeoutError()))

    def test_asyncio_timeout_is_retryable(self) -> None:
        self.assertTrue(is_retryable_error(asyncio.TimeoutError()))

    def test_connection_reset_is_retryable(self) -> None:
        self.assertTrue(is_retryable_error(ConnectionResetError()))

    def test_http_500_is_retryable(self) -> None:
        exc = Exception("Internal Server Error")
        exc.status_code = 500  # type: ignore[attr-defined]
        self.assertTrue(is_retryable_error(exc))

    def test_http_503_is_retryable(self) -> None:
        exc = Exception("Service Unavailable")
        exc.status_code = 503  # type: ignore[attr-defined]
        self.assertTrue(is_retryable_error(exc))

    def test_http_400_is_not_retryable(self) -> None:
        exc = Exception("Bad Request")
        exc.status_code = 400  # type: ignore[attr-defined]
        self.assertFalse(is_retryable_error(exc))

    def test_value_error_is_not_retryable(self) -> None:
        self.assertFalse(is_retryable_error(ValueError("bad input")))

    def test_key_error_is_not_retryable(self) -> None:
        self.assertFalse(is_retryable_error(KeyError("missing")))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
