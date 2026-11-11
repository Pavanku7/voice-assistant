"""
SkillRegistry — discovery, loading, validation, and lifecycle management.

Scans the ``skills/`` directory for subdirectories containing a
``manifest.json``, validates each manifest, dynamically imports the declared
entry point, instantiates the skill, and drives its lifecycle hooks
(``on_load`` / ``on_enable`` / ``on_disable`` / ``on_unload``).

Intent patterns from enabled skills are exposed to the Intent Router.
Supports hot-reload: newly added skill directories are discovered on demand
(within 5 seconds when polled by the platform) without a restart.

Requirements addressed:
    1.1, 1.2, 1.3, 1.4, 1.5, 5.2,
    11.1, 11.2, 11.3, 11.4, 11.6, 11.7, 11.8
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from meryna_platform.models import IntentPattern
from skills.base import Skill
from skills.manifest import ManifestValidationError, load_manifest

logger = logging.getLogger("meryna.skills.registry")

# Requirement 11.7 — lifecycle hooks must complete within 30 seconds.
_LIFECYCLE_TIMEOUT_SECONDS: int = 30

MANIFEST_FILENAME = "manifest.json"


class _LoadedSkill:
    """Internal record tracking a loaded skill and its state."""

    __slots__ = ("skill", "manifest", "enabled", "directory", "load_order")

    def __init__(
        self,
        skill: Skill,
        manifest: Dict[str, Any],
        directory: str,
        load_order: int,
    ) -> None:
        self.skill = skill
        self.manifest = manifest
        self.directory = directory
        self.load_order = load_order
        self.enabled = False


class SkillRegistry:
    """Discovers, validates, and manages the lifecycle of skills.

    Parameters
    ----------
    skills_dir:
        Path to the ``skills/`` directory.
    config_manager:
        The platform :class:`~platform.config.ConfigurationManager`.
    ai_provider:
        The active AI provider (or provider manager) passed to each skill's
        constructor.
    """

    def __init__(
        self,
        skills_dir: Path,
        config_manager: Any,
        ai_provider: Any = None,
    ) -> None:
        self._skills_dir = Path(skills_dir)
        self._config = config_manager
        self._ai_provider = ai_provider

        # skill_name -> _LoadedSkill
        self._skills: Dict[str, _LoadedSkill] = {}
        # Preserves registration order for tie-breaking (Requirement 2.4)
        self._registration_order: List[str] = []
        self._load_counter = 0

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover_skills(self) -> List[str]:
        """Return the names of every skill directory containing a manifest.

        A "skill directory" is any immediate subdirectory of ``skills_dir``
        that holds a ``manifest.json`` file (Requirement 1.1).
        """
        discovered: List[str] = []
        if not self._skills_dir.exists():
            logger.warning("Skills directory %s does not exist.", self._skills_dir)
            return discovered

        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith((".", "_")):
                continue
            if (entry / MANIFEST_FILENAME).is_file():
                discovered.append(entry.name)

        logger.debug("Discovered skill directories: %s", discovered)
        return discovered

    async def load_all(self) -> List[str]:
        """Discover and load every skill directory.

        Newly discovered skills are loaded; already-loaded skills are skipped.
        Returns the list of skill names successfully loaded on this call.
        """
        loaded: List[str] = []
        for directory in await self.discover_skills():
            # Skip directories whose skill is already loaded.
            if any(ls.directory == directory for ls in self._skills.values()):
                continue
            if await self.load_skill(directory):
                # Find the name that was just loaded from this directory
                for name, ls in self._skills.items():
                    if ls.directory == directory and name not in loaded:
                        loaded.append(name)
        return loaded

    # ------------------------------------------------------------------
    # Loading / unloading
    # ------------------------------------------------------------------

    async def load_skill(self, skill_dir: str) -> bool:
        """Validate, import, instantiate, and load the skill in *skill_dir*.

        On any validation/import failure the error is logged and the skill is
        skipped without affecting other skills (Requirement 1.4).

        Returns
        -------
        bool
            ``True`` if the skill was loaded (and enabled per its config),
            ``False`` otherwise.
        """
        manifest_path = self._skills_dir / skill_dir / MANIFEST_FILENAME

        # 1. Validate the manifest (Requirement 1.3, 10.x)
        try:
            manifest = load_manifest(manifest_path)
        except ManifestValidationError as exc:
            logger.error(
                "Skipping skill in '%s': manifest validation failed — %s",
                skill_dir,
                exc,
            )
            return False

        skill_name = manifest["name"]

        # 2. Import the entry-point module and resolve the class
        try:
            skill_class = self._resolve_entry_point(
                skill_dir, manifest["entry_point"]
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Skipping skill '%s': could not import entry point '%s' — %s",
                skill_name,
                manifest["entry_point"],
                exc,
            )
            return False

        # 3. Instantiate
        try:
            skill_instance = skill_class(self._ai_provider)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Skipping skill '%s': instantiation failed — %s",
                skill_name,
                exc,
            )
            return False

        if not isinstance(skill_instance, Skill):
            logger.error(
                "Skipping skill '%s': entry point does not subclass Skill.",
                skill_name,
            )
            return False

        # 4. Register defaults with the configuration manager (Requirement 5.x)
        default_enabled = bool(manifest.get("default_enabled", True))
        try:
            self._config.register_skill_defaults(
                skill_name=skill_name,
                default_enabled=default_enabled,
                default_settings={},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("register_skill_defaults failed for %s: %s", skill_name, exc)

        # 5. Call on_load lifecycle (Requirement 11.1)
        if not await self._run_lifecycle(skill_instance, "on_load", skill_name):
            logger.error(
                "Skill '%s' on_load failed; not registering the skill.",
                skill_name,
            )
            return False

        # 6. Record the loaded skill
        self._load_counter += 1
        record = _LoadedSkill(
            skill=skill_instance,
            manifest=manifest,
            directory=skill_dir,
            load_order=self._load_counter,
        )
        self._skills[skill_name] = record
        if skill_name not in self._registration_order:
            self._registration_order.append(skill_name)

        logger.info("Loaded skill '%s' v%s.", skill_name, manifest.get("version"))

        # 7. Enable according to configuration (Requirement 5.2)
        enabled = self._is_enabled_in_config(skill_name, default_enabled)
        if enabled:
            await self.enable_skill(skill_name)

        return True

    async def unload_skill(self, skill_name: str) -> bool:
        """Call ``on_unload`` and remove the skill from the registry."""
        record = self._skills.get(skill_name)
        if record is None:
            return False

        if record.enabled:
            await self._run_lifecycle(record.skill, "on_disable", skill_name)
            record.enabled = False

        await self._run_lifecycle(record.skill, "on_unload", skill_name)

        del self._skills[skill_name]
        if skill_name in self._registration_order:
            self._registration_order.remove(skill_name)
        logger.info("Unloaded skill '%s'.", skill_name)
        return True

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    async def enable_skill(self, skill_name: str) -> bool:
        """Enable *skill_name* and call its ``on_enable`` hook.

        If ``on_enable`` raises, the skill is left in the disabled state
        (Requirement 11.8).
        """
        record = self._skills.get(skill_name)
        if record is None:
            logger.warning("Cannot enable unknown skill '%s'.", skill_name)
            return False

        if record.enabled:
            return True

        ok = await self._run_lifecycle(record.skill, "on_enable", skill_name)
        if not ok:
            logger.error(
                "Skill '%s' on_enable failed; leaving skill disabled.", skill_name
            )
            record.enabled = False
            return False

        record.enabled = True
        try:
            self._config.set_skill_enabled(skill_name, True)
        except Exception:  # noqa: BLE001
            pass
        logger.info("Enabled skill '%s'.", skill_name)
        return True

    async def disable_skill(self, skill_name: str) -> bool:
        """Disable *skill_name* and call its ``on_disable`` hook.

        Its intents are excluded from the router while disabled
        (Requirement 5.2).
        """
        record = self._skills.get(skill_name)
        if record is None:
            logger.warning("Cannot disable unknown skill '%s'.", skill_name)
            return False

        if not record.enabled:
            return True

        await self._run_lifecycle(record.skill, "on_disable", skill_name)
        record.enabled = False
        try:
            self._config.set_skill_enabled(skill_name, False)
        except Exception:  # noqa: BLE001
            pass
        logger.info("Disabled skill '%s'.", skill_name)
        return True

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        """Return the loaded skill instance, or ``None`` if not loaded."""
        record = self._skills.get(skill_name)
        return record.skill if record else None

    def get_enabled_skills(self) -> List[Skill]:
        """Return every enabled skill instance, in registration order."""
        return [
            self._skills[name].skill
            for name in self._registration_order
            if name in self._skills and self._skills[name].enabled
        ]

    def get_all_intents(self) -> List[IntentPattern]:
        """Return intent patterns from all *enabled* skills.

        Intents preserve registration order, so the Intent Router can break
        confidence ties by first-registered skill (Requirement 2.4).
        """
        patterns: List[IntentPattern] = []
        for name in self._registration_order:
            record = self._skills.get(name)
            if record is None or not record.enabled:
                continue
            for intent in record.manifest.get("intents", []):
                patterns.append(
                    IntentPattern(
                        skill_name=name,
                        intent_name=intent["intent_name"],
                        description=intent.get("description", ""),
                        example_utterances=list(
                            intent.get("example_utterances", [])
                        ),
                    )
                )
        return patterns

    def get_skill_for_intent(self, intent_name: str) -> Optional[Skill]:
        """Return the enabled skill that declares *intent_name*, if any."""
        for name in self._registration_order:
            record = self._skills.get(name)
            if record is None or not record.enabled:
                continue
            for intent in record.manifest.get("intents", []):
                if intent.get("intent_name") == intent_name:
                    return record.skill
        return None

    @property
    def loaded_skill_names(self) -> List[str]:
        """Names of all loaded skills, in registration order."""
        return list(self._registration_order)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def unload_all(self) -> None:
        """Unload every skill in reverse load order (Requirement 11.4)."""
        for name in sorted(
            list(self._skills.keys()),
            key=lambda n: self._skills[n].load_order,
            reverse=True,
        ):
            await self.unload_skill(name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_entry_point(self, skill_dir: str, entry_point: str) -> type:
        """Import ``module:ClassName`` from within the skill's package.

        The entry-point module is resolved relative to ``skills.<skill_dir>``
        so a manifest ``entry_point`` of ``weather:WeatherSkill`` maps to the
        module ``skills.weather.weather`` and class ``WeatherSkill``.
        """
        module_part, _, class_name = entry_point.partition(":")

        candidates = [
            f"skills.{skill_dir}.{module_part}",
            f"skills.{module_part}",
            module_part,
        ]

        last_error: Optional[Exception] = None
        for module_name in candidates:
            try:
                module = importlib.import_module(module_name)
                return getattr(module, class_name)
            except (ImportError, AttributeError) as exc:
                last_error = exc
                continue

        raise ImportError(
            f"could not import '{class_name}' from any of {candidates}: "
            f"{last_error}"
        )

    def _is_enabled_in_config(self, skill_name: str, default_enabled: bool) -> bool:
        """Look up the enabled state from configuration, falling back to default."""
        try:
            cfg = self._config.get_skill_config(skill_name)
            if cfg is not None:
                return bool(cfg.enabled)
        except Exception:  # noqa: BLE001
            pass
        return default_enabled

    async def _run_lifecycle(
        self,
        skill: Skill,
        hook_name: str,
        skill_name: str,
    ) -> bool:
        """Run a lifecycle *hook* with a 30-second timeout.

        Logs and swallows exceptions/timeouts so one misbehaving skill does
        not affect others (Requirements 11.6, 11.7).

        Returns ``True`` if the hook completed without error, ``False``
        otherwise.
        """
        hook = getattr(skill, hook_name, None)
        if hook is None:
            return True

        try:
            await asyncio.wait_for(hook(), timeout=_LIFECYCLE_TIMEOUT_SECONDS)
            return True
        except asyncio.TimeoutError:
            logger.error(
                "Lifecycle '%s' for skill '%s' timed out after %d seconds.",
                hook_name,
                skill_name,
                _LIFECYCLE_TIMEOUT_SECONDS,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Lifecycle '%s' for skill '%s' raised %s: %s",
                hook_name,
                skill_name,
                type(exc).__name__,
                exc,
            )
            return False
