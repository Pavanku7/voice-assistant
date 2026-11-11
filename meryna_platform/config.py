"""
Configuration Manager for the Meryna Voice Platform.

Handles platform and skill configuration with validation, persistence,
change-listener notification, and hot-reload support (changes take effect
within 5 seconds without requiring a platform restart).

Config file: ~/meryna_config.json  (or a custom directory passed to __init__)
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from meryna_platform.models import SkillConfig

logger = logging.getLogger(__name__)


class ConfigurationManager:
    """Manages platform and skill configuration.

    Thread-safe: all public methods acquire ``_lock`` before mutating state.
    Change listeners are called *after* the lock is released to prevent
    deadlocks when a listener calls back into ``ConfigurationManager``.

    Configuration changes applied by :meth:`set`, :meth:`set_skill_enabled`,
    and :meth:`set_skill_setting` take effect immediately (within 5 seconds
    per Requirement 5.4) without requiring a platform restart.
    """

    CONFIG_FILE = "meryna_config.json"

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        """Initialise with *config_dir* (defaults to the user's home directory)."""
        self._config_dir: Path = config_dir if config_dir is not None else Path.home()
        self._config_path: Path = self._config_dir / self.CONFIG_FILE

        # General platform config (key → value)
        self._config: Dict[str, Any] = {}
        # Per-skill config (skill_name → SkillConfig)
        self._skill_configs: Dict[str, SkillConfig] = {}
        # Defaults registered by each skill at load time
        self._skill_defaults: Dict[str, Dict[str, Any]] = {}

        self._change_listeners: List[Callable[[str, Any], None]] = []
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config_path(self) -> Path:
        """Return the resolved path to the configuration file."""
        return self._config_path

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Load configuration from ``meryna_config.json``.

        If the file does not exist or cannot be read/parsed, a *default*
        configuration is created (all skills set to their ``default_enabled``
        state as defined in their Skill_Manifest) and written to disk
        (Requirement 5.7).

        Returns ``True`` on success (file read or new default file created),
        ``False`` only when the default file cannot be written either.
        """
        with self._lock:
            try:
                if not self._config_path.exists():
                    logger.info(
                        "Config file not found at %s — creating default.",
                        self._config_path,
                    )
                    return self._create_default_config()

                raw = self._config_path.read_text(encoding="utf-8")
                data = json.loads(raw)

                self._config = data.get("platform", {})
                skills_data: Dict[str, Any] = data.get("skills", {})

                for skill_name, skill_data in skills_data.items():
                    self._skill_configs[skill_name] = SkillConfig(
                        name=skill_name,
                        enabled=bool(skill_data.get("enabled", True)),
                        settings=dict(skill_data.get("settings", {})),
                    )

                logger.info("Configuration loaded from %s.", self._config_path)
                return True

            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.warning(
                    "Cannot read config file (%s: %s) — creating default.",
                    type(exc).__name__,
                    exc,
                )
                return self._create_default_config()

    def save(self) -> bool:
        """Persist current configuration to ``meryna_config.json``.

        Returns ``True`` on success, ``False`` on I/O error.
        """
        with self._lock:
            try:
                self._config_dir.mkdir(parents=True, exist_ok=True)
                data = {
                    "platform": self._config,
                    "skills": {
                        name: {
                            "enabled": sc.enabled,
                            "settings": sc.settings,
                        }
                        for name, sc in self._skill_configs.items()
                    },
                }
                self._config_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                logger.debug("Configuration saved to %s.", self._config_path)
                return True

            except OSError as exc:
                logger.error("Failed to save configuration: %s", exc)
                return False

    # ------------------------------------------------------------------
    # General key/value access
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the platform config value for *key*, or *default*."""
        with self._lock:
            return self._config.get(key, default)

    def set(
        self,
        key: str,
        value: Any,
        schema: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Set a platform config *key* to *value*.

        If *schema* is provided the value is validated against it before
        being applied.  On validation failure the previous value is
        **retained** and a warning is logged (Requirement 5.6).

        Notifies registered change listeners on success (Requirement 5.8).

        Returns ``True`` on success, ``False`` on validation failure.
        """
        with self._lock:
            previous_value = self._config.get(key)

            if schema is not None:
                error = self._validate_value(value, schema)
                if error:
                    logger.warning(
                        "Validation failure for platform.%s: %s  "
                        "Retaining previous value: %r.",
                        key,
                        error,
                        previous_value,
                    )
                    return False

            self._config[key] = value
            listeners = list(self._change_listeners)

        self._notify_listeners(listeners, f"platform.{key}", value)
        logger.info(
            "Configuration updated: platform.%s = %r — change applied successfully.",
            key,
            value,
        )
        return True

    # ------------------------------------------------------------------
    # Skill-specific access
    # ------------------------------------------------------------------

    def get_skill_config(self, skill_name: str) -> Optional[SkillConfig]:
        """Return the :class:`SkillConfig` for *skill_name*, or ``None``."""
        with self._lock:
            return self._skill_configs.get(skill_name)

    def set_skill_enabled(self, skill_name: str, enabled: bool) -> bool:
        """Enable or disable *skill_name*.

        Creates a default :class:`SkillConfig` if none exists yet.
        Notifies change listeners and confirms the change via log
        (Requirement 5.8).

        Returns ``True`` on success.
        """
        with self._lock:
            if skill_name not in self._skill_configs:
                defaults = self._skill_defaults.get(skill_name, {})
                self._skill_configs[skill_name] = SkillConfig(
                    name=skill_name,
                    enabled=defaults.get("default_enabled", True),
                    settings=dict(defaults.get("default_settings", {})),
                )
            self._skill_configs[skill_name].enabled = enabled
            listeners = list(self._change_listeners)

        change_key = f"skills.{skill_name}.enabled"
        self._notify_listeners(listeners, change_key, enabled)
        logger.info(
            "Configuration updated: %s = %r — change applied successfully.",
            change_key,
            enabled,
        )
        return True

    def set_skill_setting(
        self,
        skill_name: str,
        key: str,
        value: Any,
        schema: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Set *key* in *skill_name*'s settings to *value*.

        If *schema* is provided the value is validated against it before
        being applied.  On validation failure the previous value is
        **retained** and the user is notified via a WARNING log message
        (Requirement 5.6).

        Notifies change listeners on success (Requirement 5.8).

        Returns ``True`` on success, ``False`` on validation failure.
        """
        with self._lock:
            # Ensure the skill config record exists
            if skill_name not in self._skill_configs:
                defaults = self._skill_defaults.get(skill_name, {})
                self._skill_configs[skill_name] = SkillConfig(
                    name=skill_name,
                    enabled=defaults.get("default_enabled", True),
                    settings=dict(defaults.get("default_settings", {})),
                )

            skill_cfg = self._skill_configs[skill_name]
            previous_value = skill_cfg.settings.get(key)

            # Validate against schema if provided
            if schema is not None:
                error = self._validate_value(value, schema)
                if error:
                    logger.warning(
                        "Validation failure for skills.%s.settings.%s: %s  "
                        "Retaining previous value: %r.",
                        skill_name,
                        key,
                        error,
                        previous_value,
                    )
                    return False

            skill_cfg.settings[key] = value
            listeners = list(self._change_listeners)

        change_key = f"skills.{skill_name}.settings.{key}"
        self._notify_listeners(listeners, change_key, value)
        logger.info(
            "Configuration updated: %s = %r — change applied successfully.",
            change_key,
            value,
        )
        return True

    # ------------------------------------------------------------------
    # Skill default registration & listener registration
    # ------------------------------------------------------------------

    def register_skill_defaults(
        self,
        skill_name: str,
        default_enabled: bool,
        default_settings: Dict[str, Any],
    ) -> None:
        """Register default configuration for *skill_name*.

        Called by the Skill Registry when a skill is first loaded.  If the
        skill has no entry in the loaded config yet, a new
        :class:`SkillConfig` is created from these defaults so that all
        skills start at their ``default_enabled`` state (Requirement 5.7).
        """
        with self._lock:
            self._skill_defaults[skill_name] = {
                "default_enabled": default_enabled,
                "default_settings": default_settings,
            }

            if skill_name not in self._skill_configs:
                self._skill_configs[skill_name] = SkillConfig(
                    name=skill_name,
                    enabled=default_enabled,
                    settings=dict(default_settings),
                )
                logger.debug(
                    "Registered defaults for new skill '%s' (enabled=%s).",
                    skill_name,
                    default_enabled,
                )

    def on_change(self, callback: Callable[[str, Any], None]) -> None:
        """Register *callback* to be called whenever a config value changes.

        The callback signature is ``callback(key: str, value: Any) -> None``
        where *key* is the dot-separated configuration path, for example:

        - ``"platform.ai_provider"``
        - ``"skills.weather.enabled"``
        - ``"skills.weather.settings.units"``

        Callbacks are invoked outside the internal lock to avoid deadlocks
        when a listener calls back into :class:`ConfigurationManager`.
        """
        with self._lock:
            if callback not in self._change_listeners:
                self._change_listeners.append(callback)

    def remove_change_listener(self, callback: Callable[[str, Any], None]) -> bool:
        """Unregister a previously registered change *callback*.

        Returns ``True`` if the callback was found and removed, ``False``
        if it was not registered.
        """
        with self._lock:
            try:
                self._change_listeners.remove(callback)
                return True
            except ValueError:
                return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_default_config(self) -> bool:
        """Write an empty/default config (skills at their defaults) and load it.

        Returns ``True`` when the file is written successfully.
        """
        self._config = {}
        # Build skill configs from any already-registered defaults
        for skill_name, defaults in self._skill_defaults.items():
            if skill_name not in self._skill_configs:
                self._skill_configs[skill_name] = SkillConfig(
                    name=skill_name,
                    enabled=defaults.get("default_enabled", True),
                    settings=dict(defaults.get("default_settings", {})),
                )
        return self.save()

    @staticmethod
    def _validate_value(value: Any, schema: Dict[str, Any]) -> Optional[str]:
        """Validate *value* against a JSON-schema-like *schema* dict.

        Supports: ``type``, ``minimum``, ``maximum``, ``minLength``,
        ``maxLength``, ``enum``, and ``pattern``.

        Special note: ``"integer"`` type rejects Python ``bool`` values
        (since ``bool`` is a subclass of ``int`` in Python).

        Returns an error message string on failure, or ``None`` on success.
        """
        expected_type_str: Optional[str] = schema.get("type")
        if expected_type_str is not None:
            type_map: Dict[str, Any] = {
                "string": str,
                "integer": int,
                "number": (int, float),
                "boolean": bool,
                "array": list,
                "object": dict,
                "null": type(None),
            }
            expected_type = type_map.get(expected_type_str)
            if expected_type is not None:
                # Special-case: bool is a subclass of int in Python; treat them
                # as distinct types so {"type": "integer"} rejects True/False.
                if expected_type_str == "integer" and isinstance(value, bool):
                    return (
                        f"expected type 'integer', "
                        f"got '{type(value).__name__}'"
                    )
                if expected_type_str == "number" and isinstance(value, bool):
                    return (
                        f"expected type 'number', "
                        f"got '{type(value).__name__}'"
                    )
                if not isinstance(value, expected_type):
                    return (
                        f"expected type '{expected_type_str}', "
                        f"got '{type(value).__name__}'"
                    )

        if "enum" in schema and value not in schema["enum"]:
            return f"value {value!r} is not one of {schema['enum']}"

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                return f"value {value} is below minimum {schema['minimum']}"
            if "maximum" in schema and value > schema["maximum"]:
                return f"value {value} is above maximum {schema['maximum']}"

        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                return (
                    f"string length {len(value)} is below "
                    f"minLength {schema['minLength']}"
                )
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                return (
                    f"string length {len(value)} exceeds "
                    f"maxLength {schema['maxLength']}"
                )
            if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
                return (
                    f"value {value!r} does not match pattern "
                    f"'{schema['pattern']}'"
                )

        return None

    @staticmethod
    def _notify_listeners(
        listeners: List[Callable[[str, Any], None]],
        key: str,
        value: Any,
    ) -> None:
        """Invoke each listener with *key* and *value*.

        Exceptions raised by listeners are caught and logged so that a
        misbehaving listener cannot prevent other listeners from being called.
        """
        for cb in listeners:
            try:
                cb(key, value)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Change listener %r raised an exception for key %r: %s",
                    cb,
                    key,
                    exc,
                )
