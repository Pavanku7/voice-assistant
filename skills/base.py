"""
Abstract base class for all Meryna skills.

Every skill must extend ``Skill`` and implement the three abstract members:
  - ``name`` property  (str)
  - ``version`` property  (str)
  - ``execute(context)`` coroutine

All lifecycle hooks (``on_load``, ``on_enable``, ``on_disable``, ``on_unload``)
have default no-op implementations so skill authors only override what they need.

Requirements: 1.6, 11.5
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse


class Skill(ABC):
    """Abstract base class that all Meryna skills must extend.

    Parameters
    ----------
    ai_provider:
        The platform's active AI provider, typed as ``Any`` to avoid a
        circular import between the ``skills`` and ``ai`` packages.
        At runtime this will be an ``ai.provider.AIProvider`` instance.
    """

    def __init__(self, ai_provider: Any) -> None:
        self._ai_provider = ai_provider

    # ------------------------------------------------------------------
    # Abstract identity properties
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill identifier, matching the ``name`` field in ``manifest.json``."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string (MAJOR.MINOR.PATCH) from ``manifest.json``."""

    # ------------------------------------------------------------------
    # Abstract execution entry-point
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self, context: SkillContext) -> SkillResponse:
        """Process a user utterance and return a response.

        Parameters
        ----------
        context:
            Runtime context containing the utterance, resolved intent,
            extracted entities, conversation history, user preferences,
            and the current session identifier.

        Returns
        -------
        SkillResponse
            The skill's text response plus optional session-control flags.
        """

    # ------------------------------------------------------------------
    # Lifecycle hooks — default no-op implementations (Requirement 11.5)
    # ------------------------------------------------------------------

    async def on_load(self) -> None:
        """Called by the Skill Registry when the skill is first loaded.

        Override to perform one-time initialisation (e.g. opening a
        database connection or loading a model into memory).
        """

    async def on_enable(self) -> None:
        """Called by the Skill Registry when the skill is enabled.

        Override to perform setup that should run each time the skill
        transitions from disabled → enabled.
        """

    async def on_disable(self) -> None:
        """Called by the Skill Registry when the skill is disabled.

        Override to perform cleanup (e.g. pausing background tasks)
        each time the skill transitions from enabled → disabled.
        """

    async def on_unload(self) -> None:
        """Called by the Skill Registry during platform shutdown.

        Override to release resources acquired in ``on_load``
        (e.g. closing connections, flushing buffers).
        """
