"""
Skill manifest loading and validation for the Meryna Voice Platform.

This module provides:
  - ``ManifestValidationError`` — custom exception for any manifest problem
  - ``validate_manifest(data)`` — validates a parsed manifest dict in place
  - ``load_manifest(manifest_path)`` — reads a JSON file and calls validate_manifest

All validation rules are drawn directly from Requirement 10 (sections 10.1–10.7):

  10.1  Manifest is a JSON file named manifest.json in the skill's root directory.
  10.2  Required fields: name, version, description, entry_point, intents.
  10.3  Optional fields: permissions, configuration_schema, dependencies.
  10.4  entry_point format: ``module_name:ClassName``
  10.5  intents: array, each item has intent_name, description, example_utterances (≥3).
  10.6  permissions: subset of allowed values.
  10.7  Reject on invalid JSON, missing fields, or format violations with a descriptive error.

Requirements: 1.3, 1.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ENTRY_POINT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*:[A-Z][a-zA-Z0-9_]*$")

_ALLOWED_PERMISSIONS: frozenset[str] = frozenset(
    {
        "file_system",
        "network",
        "user_data",
        "audio_input",
        "audio_output",
        "system_settings",
    }
)

_REQUIRED_FIELDS = ("name", "version", "description", "entry_point", "intents")
_INTENT_REQUIRED_FIELDS = ("intent_name", "description", "example_utterances")


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ManifestValidationError(Exception):
    """Raised when a skill manifest fails validation.

    The message always identifies which field failed and why, so the Skill
    Registry can log a descriptive error without exposing internal details.

    Examples
    --------
    >>> raise ManifestValidationError("name", "must match ^[a-zA-Z0-9_-]{1,64}$, got 'bad name!'")
    ManifestValidationError: Field 'name': must match ^[a-zA-Z0-9_-]{1,64}$, got 'bad name!'
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"Field '{field}': {reason}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_required_string(
    data: Dict[str, Any],
    field: str,
    min_len: int = 1,
    max_len: int | None = None,
    pattern: re.Pattern[str] | None = None,
) -> None:
    """Validate that *field* is a non-empty string with optional length / pattern constraints."""
    if field not in data:
        raise ManifestValidationError(field, "required field is missing")

    value = data[field]
    if not isinstance(value, str):
        raise ManifestValidationError(
            field, f"must be a string, got {type(value).__name__}"
        )

    if len(value) < min_len:
        raise ManifestValidationError(
            field,
            f"must be at least {min_len} character(s) long, got {len(value)}",
        )

    if max_len is not None and len(value) > max_len:
        raise ManifestValidationError(
            field,
            f"must be at most {max_len} characters long, got {len(value)}",
        )

    if pattern is not None and not pattern.match(value):
        raise ManifestValidationError(
            field,
            f"must match pattern {pattern.pattern!r}, got {value!r}",
        )


def _validate_intent(intent: Any, index: int) -> None:
    """Validate a single intent object inside the ``intents`` array."""
    context = f"intents[{index}]"

    if not isinstance(intent, dict):
        raise ManifestValidationError(
            context, f"must be an object, got {type(intent).__name__}"
        )

    for required in _INTENT_REQUIRED_FIELDS:
        if required not in intent:
            raise ManifestValidationError(
                f"{context}.{required}", "required field is missing"
            )

    # intent_name: non-empty string
    if not isinstance(intent["intent_name"], str) or not intent["intent_name"].strip():
        raise ManifestValidationError(
            f"{context}.intent_name", "must be a non-empty string"
        )

    # description: non-empty string
    if (
        not isinstance(intent["description"], str)
        or not intent["description"].strip()
    ):
        raise ManifestValidationError(
            f"{context}.description", "must be a non-empty string"
        )

    # example_utterances: list with at least 3 non-empty strings
    utterances = intent["example_utterances"]
    if not isinstance(utterances, list):
        raise ManifestValidationError(
            f"{context}.example_utterances",
            f"must be an array, got {type(utterances).__name__}",
        )

    if len(utterances) < 3:
        raise ManifestValidationError(
            f"{context}.example_utterances",
            f"must contain at least 3 example utterances, got {len(utterances)}",
        )

    for utt_idx, utt in enumerate(utterances):
        if not isinstance(utt, str) or not utt.strip():
            raise ManifestValidationError(
                f"{context}.example_utterances[{utt_idx}]",
                "must be a non-empty string",
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_manifest(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a parsed manifest dictionary and return it unchanged on success.

    Checks every rule from Requirements 10.2–10.7:

    - **name**: 1–64 alphanumeric characters, hyphens, or underscores
      (``^[a-zA-Z0-9_-]{1,64}$``)
    - **version**: semantic version ``MAJOR.MINOR.PATCH`` (``^\\d+\\.\\d+\\.\\d+$``)
    - **description**: 1–500 characters
    - **entry_point**: ``module_path:ClassName`` where the module path is a
      valid dotted Python identifier and the class name starts with an
      uppercase letter (``^[a-zA-Z_][a-zA-Z0-9_.]*:[A-Z][a-zA-Z0-9_]*$``)
    - **intents**: non-empty array; each item must have ``intent_name``,
      ``description``, and ``example_utterances`` (≥3 phrases)
    - **permissions** *(optional)*: list restricted to the six allowed values

    Parameters
    ----------
    data:
        A ``dict`` produced by ``json.loads`` / ``json.load``.

    Returns
    -------
    dict
        The same *data* dict, unmodified, if all validations pass.

    Raises
    ------
    ManifestValidationError
        With a human-readable message identifying the failing field and reason.
    TypeError
        If *data* is not a ``dict``.
    """
    if not isinstance(data, dict):
        raise ManifestValidationError(
            "<root>", f"manifest must be a JSON object, got {type(data).__name__}"
        )

    # -- Required string fields ------------------------------------------

    _check_required_string(data, "name", min_len=1, max_len=64, pattern=_NAME_RE)
    _check_required_string(data, "version", pattern=_VERSION_RE)
    _check_required_string(data, "description", min_len=1, max_len=500)
    _check_required_string(data, "entry_point", pattern=_ENTRY_POINT_RE)

    # -- intents ---------------------------------------------------------

    if "intents" not in data:
        raise ManifestValidationError("intents", "required field is missing")

    intents = data["intents"]
    if not isinstance(intents, list):
        raise ManifestValidationError(
            "intents", f"must be an array, got {type(intents).__name__}"
        )

    if len(intents) < 1:
        raise ManifestValidationError(
            "intents", "must contain at least 1 intent"
        )

    for idx, intent in enumerate(intents):
        _validate_intent(intent, idx)

    # -- permissions (optional) ------------------------------------------

    if "permissions" in data:
        permissions = data["permissions"]
        if not isinstance(permissions, list):
            raise ManifestValidationError(
                "permissions",
                f"must be an array, got {type(permissions).__name__}",
            )

        for perm in permissions:
            if not isinstance(perm, str):
                raise ManifestValidationError(
                    "permissions",
                    f"each permission must be a string, got {type(perm).__name__}: {perm!r}",
                )
            if perm not in _ALLOWED_PERMISSIONS:
                sorted_allowed = sorted(_ALLOWED_PERMISSIONS)
                raise ManifestValidationError(
                    "permissions",
                    f"unknown permission {perm!r}; allowed values are: "
                    f"{sorted_allowed}",
                )

    # -- optional fields (configuration_schema, dependencies) are not
    #    further validated here — the registry may inspect them separately

    return data


def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Read *manifest_path*, parse JSON, and return the validated manifest dict.

    Parameters
    ----------
    manifest_path:
        Path to the ``manifest.json`` file (Requirement 10.1).

    Returns
    -------
    dict
        The validated manifest data.

    Raises
    ------
    ManifestValidationError
        - If the file cannot be read (``file`` field with the OS error message)
        - If the file contains invalid JSON (``json`` field with parse details)
        - If any manifest field fails validation (field name with reason)
    """
    # 1. Read the file
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestValidationError(
            "file",
            f"cannot read manifest at {manifest_path!r}: {exc}",
        ) from exc

    # 2. Parse JSON — Requirement 10.7: malformed JSON must produce a descriptive error
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestValidationError(
            "json",
            f"invalid JSON in {manifest_path!r}: {exc}",
        ) from exc

    # 3. Validate content
    return validate_manifest(data)
