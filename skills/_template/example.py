"""
ExampleSkill — a copy-paste starting point for building a new skill.

To create your own skill, copy the whole ``skills/_template/`` folder to
``skills/<your-skill>/``, then:

  1. Rename ``example.py`` to something meaningful (e.g. ``timer.py``).
  2. Rename the class (``ExampleSkill`` → ``TimerSkill``) and update the
     ``name`` / ``version`` properties.
  3. Write your logic inside ``execute()``.
  4. Update ``manifest.json`` — especially ``name``, ``entry_point``
     (``<module>:<ClassName>``), and the ``example_utterances`` (these teach
     the AI when to route to your skill).

That's all — no core files need editing.  Restart Meryna and the Skill
Registry auto-discovers the new folder.

The ``skills/_template/`` folder itself is IGNORED by the registry because its
name starts with an underscore, so this example never loads as a real skill.
"""

from __future__ import annotations

import logging
from typing import Any

from meryna_platform.models import SkillContext, SkillResponse
from skills.base import Skill

logger = logging.getLogger("meryna.skills.example")


class ExampleSkill(Skill):
    """A minimal skill showing every piece you have to work with."""

    def __init__(self, ai_provider: Any) -> None:
        # ai_provider is the platform's AI (Gemini/Claude). Optional to use.
        super().__init__(ai_provider)

    # -- Identity (must match manifest.json) ---------------------------

    @property
    def name(self) -> str:
        # MUST equal the "name" field in manifest.json.
        return "example-skill"

    @property
    def version(self) -> str:
        return "1.0.0"

    # -- Main entry point ----------------------------------------------

    async def execute(self, context: SkillContext) -> SkillResponse:
        """Handle one request and return what Meryna should say.

        The ``context`` gives you everything about the request:

          context.utterance             -> str: exactly what the user said
          context.intent_name           -> str: the matched intent
          context.entities              -> dict: values the AI pulled out,
                                           e.g. {"location": "Mumbai"}
          context.conversation_history  -> list[dict]: recent turns
          context.user_preferences      -> dict: e.g. {"name": "...",
                                           "location": "..."}
          context.session_id            -> str

        You can also call the AI provider if your skill needs generation:

          reply = await self._ai_provider.generate_text(
              prompt=context.utterance,
              conversation_history=context.conversation_history,
          )

        Whatever text you return is spoken aloud, so keep it TTS-friendly:
        no markdown, asterisks, or headers.
        """
        user_said = context.utterance

        # ---- Your logic goes here. This is just a placeholder reply. ----
        reply = f"This is the example skill. You said: {user_said}"

        return SkillResponse(
            text=reply,
            # Optional extras (all have sensible defaults):
            # should_end_session=False,   # True to close the session after this
            # follow_up_prompt=None,      # a question to ask next, if any
            # metadata={},                # anything you want to attach
        )

    # -- Optional lifecycle hooks (delete if you don't need them) -------
    #
    # async def on_load(self) -> None:    ...  # once, when first loaded
    # async def on_enable(self) -> None:  ...  # each time it's enabled
    # async def on_disable(self) -> None: ...  # each time it's disabled
    # async def on_unload(self) -> None:  ...  # on shutdown
