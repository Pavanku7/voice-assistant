"""
Platform-level logging for the Meryna Voice Platform.

Provides centralized, rotating file logging with per-skill prefixed loggers,
structured skill invocation records, AI request/response capture at DEBUG
level, and full-stack-trace error logging.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional


class PlatformLogger:
    """Centralized logging with skill prefixing and file rotation.

    A single ``meryna.log`` file is written to ``log_dir`` (default: the
    user's home directory).  The file rotates at 10 MB and at most 5 backup
    copies are kept.

    Skill-specific child loggers returned by :meth:`skill_logger` inherit the
    root logger's handlers and level but tag every record with the skill name
    so log lines are easy to filter.

    Requirements covered:
        12.1 – skill invocations logged with ISO 8601 timestamp, skill name,
               and response time in milliseconds.
        12.2 – AI provider requests/responses logged at DEBUG.
        12.3 – Errors logged with full stack traces at ERROR.
        12.4 – Configurable log level; default INFO.
        12.5 – Skill log messages prefixed with skill name.
        12.6 – Log rotation at 10 MB, 5 backup files retained.
    """

    LOG_FILE = "meryna.log"
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    BACKUP_COUNT = 5
    DEFAULT_LEVEL = logging.INFO

    # Internal logger name used as the root for all platform logging.
    _ROOT_LOGGER_NAME = "meryna"

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        level: int = DEFAULT_LEVEL,
    ) -> None:
        """Initialise the platform logger.

        Parameters
        ----------
        log_dir:
            Directory where ``meryna.log`` is written.  Defaults to the
            current user's home directory when *None*.
        level:
            Initial logging level.  Defaults to ``logging.INFO``.
        """
        self._log_dir: Path = log_dir if log_dir is not None else Path.home()
        self._log_path: Path = self._log_dir / self.LOG_FILE
        self._level: int = level

        # Obtain (or create) the root platform logger and configure it only
        # when it has no handlers yet so repeated instantiation in tests does
        # not multiply handlers.
        self._logger: logging.Logger = logging.getLogger(self._ROOT_LOGGER_NAME)
        self._logger.setLevel(self._level)

        if not self._logger.handlers:
            self._setup_handlers()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _setup_handlers(self) -> None:
        """Attach a rotating file handler and a console handler."""
        # Ensure the log directory exists.
        self._log_dir.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

        # Rotating file handler — Requirement 12.6.
        file_handler = RotatingFileHandler(
            filename=self._log_path,
            maxBytes=self.MAX_FILE_SIZE,
            backupCount=self.BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        # Console handler so logs are also visible during development.
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_level(self, level: int) -> None:
        """Set the log level on the root platform logger and all its handlers.

        Requirement 12.4 — supports DEBUG, INFO, WARNING, ERROR.

        Parameters
        ----------
        level:
            A ``logging`` level constant, e.g. ``logging.DEBUG``.
        """
        self._level = level
        self._logger.setLevel(level)
        for handler in self._logger.handlers:
            handler.setLevel(level)

    def log_skill_invocation(
        self,
        skill_name: str,
        utterance: str,
        response_time_ms: float,
    ) -> None:
        """Log a completed skill invocation at INFO level.

        The record includes an ISO 8601 timestamp (UTC), the skill name,
        the triggering utterance, and the end-to-end response time in
        milliseconds.

        Requirement 12.1.

        Parameters
        ----------
        skill_name:
            The name of the skill that was invoked.
        utterance:
            The user utterance that triggered the skill.
        response_time_ms:
            Total response time measured by the caller, in milliseconds.
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        self._logger.info(
            "SKILL_INVOCATION skill=%s utterance=%r response_time_ms=%.2f ts=%s",
            skill_name,
            utterance,
            response_time_ms,
            timestamp,
        )

    def log_ai_request(
        self,
        operation: str,
        request_payload: Dict[str, Any],
        response_payload: Dict[str, Any],
    ) -> None:
        """Log an AI provider request and response at DEBUG level.

        Requirement 12.2.

        Parameters
        ----------
        operation:
            A short label identifying the AI operation (e.g.
            ``"generate_text"``, ``"classify_intent"``).
        request_payload:
            The data sent to the AI provider.
        response_payload:
            The data received from the AI provider.
        """
        try:
            request_str = json.dumps(request_payload, ensure_ascii=False)
            response_str = json.dumps(response_payload, ensure_ascii=False)
        except (TypeError, ValueError):
            request_str = repr(request_payload)
            response_str = repr(response_payload)

        self._logger.debug(
            "AI_REQUEST operation=%s request=%s response=%s",
            operation,
            request_str,
            response_str,
        )

    def log_error(
        self,
        message: str,
        exception: Optional[Exception] = None,
        skill_name: Optional[str] = None,
    ) -> None:
        """Log an error with an optional full stack trace at ERROR level.

        Requirement 12.3.

        Parameters
        ----------
        message:
            A human-readable description of the error.
        exception:
            The exception that caused the error.  When supplied its full
            stack trace is appended to the log record.
        skill_name:
            When provided the log record is emitted on the skill's child
            logger so it carries the skill-name prefix (Requirement 12.5).
        """
        logger = (
            self.skill_logger(skill_name) if skill_name else self._logger
        )

        if exception is not None:
            stack = "".join(
                traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                )
            )
            logger.error("%s\n%s", message, stack)
        else:
            logger.error(message)

    def skill_logger(self, skill_name: str) -> logging.Logger:
        """Return a child logger prefixed with *skill_name*.

        The child logger shares the root platform logger's handlers and
        level.  Every log record emitted through it will carry the name
        ``meryna.<skill_name>``, making it trivial to filter log output
        per skill.

        Requirement 12.5.

        Parameters
        ----------
        skill_name:
            The skill identifier used as the logger name suffix.

        Returns
        -------
        logging.Logger
            A ``logging.Logger`` instance whose ``name`` attribute is
            ``"meryna.<skill_name>"``.
        """
        child = self._logger.getChild(skill_name)
        # Child loggers propagate to the root by default; level NOTSET means
        # they defer to the parent's effective level — which is what we want.
        child.setLevel(logging.NOTSET)
        return child
