# Adding Skills to Meryna

Meryna's abilities are **plugins**. Each skill is a self-contained folder under
[skills/](skills/) — adding a new one never requires editing any core file.
On startup the Skill Registry scans `skills/`, finds every folder with a
`manifest.json`, validates it, loads it, and the AI router starts sending
matching requests to it automatically.

---

## The fastest way — use the generator

```bash
python new_skill.py <name> [-d "Short description"]
```

Examples:
```bash
python new_skill.py timer
python new_skill.py "unit converter" -d "Converts between units of measure."
```

This creates `skills/<name>/` with all three files pre-filled. Then:
1. Open `skills/<name>/manifest.json` and refine the **description** and
   **example_utterances** (these teach the AI when to trigger the skill).
2. Write your logic in the generated `.py` file's `execute()` method.
3. Restart Meryna. Done.

---

## Doing it by hand (or understanding what the generator makes)

Every skill folder has exactly **three files**. Copy
[skills/_template/](skills/_template/) as a starting point — it's a fully
commented reference (and is ignored by the registry because its name starts
with `_`).

```
skills/timer/
├── manifest.json     # declares the skill + example phrases for routing
├── timer.py          # the logic (a class that subclasses Skill)
└── __init__.py       # empty package marker
```

### 1. `manifest.json`

```json
{
  "name": "timer-skill",
  "version": "1.0.0",
  "description": "Sets countdown timers.",
  "entry_point": "timer:TimerSkill",
  "default_enabled": true,
  "permissions": ["network"],
  "intents": [
    {
      "intent_name": "set_timer",
      "description": "Set a countdown timer for a duration.",
      "example_utterances": [
        "Set a timer for 5 minutes",
        "Start a 10 minute timer",
        "Timer for 30 seconds"
      ]
    }
  ]
}
```

| Field | Rule |
|-------|------|
| `name` | Unique. 1–64 chars, letters/digits/`-`/`_`. Must match the class's `name` property. |
| `version` | Semantic version `MAJOR.MINOR.PATCH`. |
| `description` | 1–500 chars. Shown in skill listings. |
| `entry_point` | `<module>:<ClassName>` — e.g. `timer:TimerSkill` means class `TimerSkill` in `timer.py`. |
| `default_enabled` | `true`/`false` — whether the skill is on by default. |
| `permissions` | *(optional)* subset of: `file_system`, `network`, `user_data`, `audio_input`, `audio_output`, `system_settings`. |
| `intents` | At least one. Each needs `intent_name`, `description`, and **≥3** `example_utterances`. |

> **The `example_utterances` matter most.** The AI router compares what the user
> said against these phrases to decide which skill to run. Give 4–6 realistic,
> varied examples of how people would actually ask.

### 2. The skill class (`timer.py`)

```python
from platform.models import SkillContext, SkillResponse
from skills.base import Skill


class TimerSkill(Skill):
    @property
    def name(self) -> str:
        return "timer-skill"      # MUST match manifest "name"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: SkillContext) -> SkillResponse:
        return SkillResponse(text="Timer set.")
```

### 3. `__init__.py`

Just a one-line comment — it marks the folder as a Python package:

```python
"""Timer skill package."""
```

---

## What your `execute()` receives and returns

`execute(self, context)` is called with a **`SkillContext`**:

| Attribute | Type | What it holds |
|-----------|------|---------------|
| `context.utterance` | `str` | Exactly what the user said. |
| `context.intent_name` | `str` | The matched intent. |
| `context.entities` | `dict` | Values the AI extracted, e.g. `{"location": "Mumbai"}`. |
| `context.conversation_history` | `list[dict]` | Recent turns (`role`/`content`). |
| `context.user_preferences` | `dict` | e.g. `{"name": "...", "location": "..."}`. |
| `context.session_id` | `str` | The current session. |

It must return a **`SkillResponse`**:

| Field | Default | Purpose |
|-------|---------|---------|
| `text` | *(required)* | What Meryna says. Keep it TTS-friendly — no markdown/asterisks. |
| `should_end_session` | `False` | Set `True` to close the session after this reply. |
| `follow_up_prompt` | `None` | A question to ask next, if the skill expects a reply. |
| `metadata` | `{}` | Anything extra you want to attach. |

### Using the AI inside a skill

The platform's AI provider is available as `self._ai_provider`:

```python
reply = await self._ai_provider.generate_text(
    prompt=context.utterance,
    conversation_history=context.conversation_history,
)
return SkillResponse(text=reply)
```

### Calling a network API (see the weather skill)

`execute()` is `async`. For blocking calls (`urllib`, `requests`), offload to a
thread so you don't freeze the event loop:

```python
import asyncio
data = await asyncio.to_thread(self._fetch_blocking, some_arg)
```

---

## Good to know

- **Isolation.** If a skill fails to load or raises at runtime, the registry
  logs it and skips *just that skill* — the rest of Meryna keeps working.
- **Enable / disable.** Set `default_enabled` in the manifest, or toggle a skill
  in `~/meryna_config.json` without deleting code.
- **Shared helpers** (used by more than one skill) go in a plain module like
  [skills/geolocation.py](skills/geolocation.py) — a *file*, not a folder, so the
  registry doesn't mistake it for a skill. Ready-made helpers you can reuse:
  - [skills/websearch.py](skills/websearch.py) — `search(query)` returns web
    results via DuckDuckGo (free, no API key). Call it from a thread:
    `found = await asyncio.to_thread(websearch.search, query)`.
  - [skills/userstore.py](skills/userstore.py) — a tiny persistent JSON store
    (`get_list`/`add_item`/`clear` under a namespace) for skills that must
    remember items between sessions, like notes and reminders.
  - [i18n.py](i18n.py) — `detect_language(text)`, `voice_for_language(...)`,
    `stt_code(...)`. Language is auto-detected, so you rarely need this
    directly: just return your answer in the user's language (the AI already
    replies in-language, and the TTS voice adapts automatically).
- **Underscore folders are ignored.** `skills/_template/` (and anything starting
  with `_` or `.`) is never loaded as a skill.
- **The fallback.** Anything that doesn't match a specific skill goes to
  `conversation-skill`, which answers with the AI.

---

## Optional lifecycle hooks

Override any of these on your skill class if you need setup/teardown (all
default to no-ops, so you only add what you use):

```python
async def on_load(self):    ...  # once, when first loaded
async def on_enable(self):  ...  # each time it's enabled
async def on_disable(self): ...  # each time it's disabled
async def on_unload(self):  ...  # on shutdown
```
