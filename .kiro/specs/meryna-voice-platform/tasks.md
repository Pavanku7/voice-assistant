# Implementation Plan: Meryna Voice Platform

## Overview

Restructure the existing Meryna voice assistant from a monolithic implementation into a scalable, plugin-based platform modelled after Amazon Alexa. The implementation follows the layered directory structure defined in the design: `platform/`, `skills/`, `ai/`, `voice/`, `memory/`, and `interfaces/`. Each phase builds on the previous, ending with fully wired web and CLI interfaces that share the same skill infrastructure.

## Tasks

- [x] 1. Set up project structure and core data types
  - Create the full directory structure: `platform/`, `skills/`, `ai/`, `voice/voice/stt/`, `voice/tts/`, `memory/`, `interfaces/web/`, `interfaces/cli/`
  - Add `__init__.py` files to every package directory
  - Define shared dataclasses in `platform/models.py`: `PlatformResponse`, `SkillContext`, `SkillResponse`, `IntentPattern`, `RoutingResult`, `IntentClassification`, `EntityExtraction`, `VoiceConfig`, `UserPreferences`, `ConversationTurn`, `ConversationState`, `SkillConfig`, `PlatformError`
  - Define `ErrorCategory` enum in `platform/models.py`
  - _Requirements: 1.6, 2.4, 3.1, 4.5, 6.5, 8.1_

- [x] 2. Implement Configuration Manager
  - [x] 2.1 Implement `ConfigurationManager` class in `platform/config.py`
    - Write `load()` that reads `meryna_config.json`; creates a default config file (all skills set to their `default_enabled` state) when the file is missing or unreadable
    - Write `save()` to persist configuration
    - Write `get()` / `set()` with validation and change-listener notification
    - Write `get_skill_config()`, `set_skill_enabled()`, `set_skill_setting()` with schema validation; retain previous value and notify user on validation failure
    - Write `register_skill_defaults()` and `on_change()` callback registration
    - Apply changes within 5 seconds without platform restart
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [ ]* 2.2 Write unit tests for ConfigurationManager
    - Test default config creation when file is missing
    - Test validation rejects bad values and retains previous value
    - Test change listeners are notified on successful `set()`
    - _Requirements: 5.5, 5.6, 5.7_

- [x] 3. Implement Platform Logger
  - [x] 3.1 Implement `PlatformLogger` class in `platform/logging.py`
    - Configure `RotatingFileHandler` with `MAX_FILE_SIZE=10 MB`, `BACKUP_COUNT=5`
    - Implement `log_skill_invocation()` with ISO 8601 timestamp, skill name, and response time in ms
    - Implement `log_ai_request()` at DEBUG level with request/response payloads
    - Implement `log_error()` with full stack trace at ERROR level
    - Implement `set_level()` and `skill_logger()` for per-skill prefixed loggers
    - Default log level: INFO
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ]* 3.2 Write unit tests for PlatformLogger
    - Test log rotation triggers at 10 MB and retains at most 5 backup files
    - Test skill invocation log includes timestamp, skill name, and response time
    - Test `skill_logger()` prefixes messages with skill name
    - _Requirements: 12.1, 12.5, 12.6_

- [x] 4. Implement Error Handler
  - [x] 4.1 Implement `ErrorHandler` class in `platform/errors.py`
    - Implement `handle_skill_error()` with circuit-breaker logic: disable skill for 5 minutes after 3 consecutive errors within a 5-minute window
    - Implement `handle_ai_error()` with user-safe messages for rate-limit, auth, and network errors
    - Implement `is_skill_disabled()` and `reset_skill_errors()`
    - Implement `with_retry()` with exponential backoff: max 3 retries, initial delay 1 s, max delay 30 s, for network timeouts / connection resets / HTTP 5xx
    - Implement `to_user_message()` — never expose stack traces, file paths, function names, or API credentials
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [ ]* 4.2 Write unit tests for ErrorHandler
    - Test circuit breaker disables skill after 3 errors within the window
    - Test exponential backoff delays increase correctly up to 30 s
    - Test `to_user_message()` never leaks internal details
    - _Requirements: 8.4, 8.5, 8.6_

- [x] 5. Checkpoint — Core infrastructure
  - Ensure all tests for tasks 2–4 pass. Ask the user if any questions arise before continuing.

- [x] 6. Implement Memory Manager and Context Manager
  - [x] 6.1 Implement `MemoryManager` in `memory/manager.py`
    - Write `load()`: reads `.meryna_memory.json` from the user's home directory (configurable); falls back to in-memory-only mode with a warning log if the storage path is unavailable; discards corrupted data and starts with empty history, logging a warning
    - Write `save()`: retains data in memory on write failure and retries on the next save attempt, logging a warning
    - Write `add_turn()`, `get_history()`, `get_preferences()`, `set_preferences()` with field validation (name ≤ 50 chars, location ≤ 100 chars, speech_rate 50–300, volume 0.0–1.0)
    - Enforce `history_limit` (default 30 turns)
    - _Requirements: 6.1, 6.2, 6.5, 6.6, 6.7, 6.8_

  - [x] 6.2 Implement `ContextManager` in `memory/context.py`
    - Write `get_skill_context()`: returns last 10 conversation turns and all user preferences
    - Write `set_active_skill()`, `get_active_skill()`, `add_follow_up()` (max 5 items), `pop_follow_up()`, `clear_state()`, `set_session_data()`, `get_session_data()`
    - _Requirements: 6.3, 6.4_

  - [ ]* 6.3 Write unit tests for MemoryManager and ContextManager
    - Test in-memory fallback when storage path is unavailable
    - Test corrupted JSON triggers fresh start with warning log
    - Test `add_follow_up()` rejects a 6th item
    - Test `get_skill_context()` returns at most 10 turns
    - _Requirements: 6.3, 6.6, 6.7, 6.8_

- [x] 7. Implement AI Provider layer
  - [x] 7.1 Implement `AIProvider` abstract base class in `ai/provider.py`
    - Define abstract methods: `generate_text()`, `classify_intent()`, `extract_entities()`, `initialize()`, `health_check()`
    - _Requirements: 3.1_

  - [x] 7.2 Implement `GeminiProvider` in `ai/gemini.py`
    - Wrap the `google-genai` client already used in `Meryna.py`
    - Implement `generate_text()` including system prompt (max 4000 chars) and last 20 messages of conversation history
    - Implement `classify_intent()` and `extract_entities()` using structured prompts
    - Implement `initialize()` with a 30-second timeout; log failure and raise on timeout or connection error
    - _Requirements: 3.1, 3.2, 3.3, 3.7, 3.8_

  - [x] 7.3 Implement `ClaudeProvider` in `ai/claude.py`
    - Wrap the `anthropic` client already used in `meryna_brain.py`
    - Match the same interface as `GeminiProvider`
    - _Requirements: 3.1, 3.2, 3.3, 3.7, 3.8_

  - [x] 7.4 Implement `AIProviderManager` in `ai/manager.py`
    - Read primary and fallback provider configs from `ConfigurationManager`
    - Implement `initialize()` with 30-second timeout; log failure and report initialization error if exceeded
    - Implement `generate_text()` and `classify_intent()` with automatic fallback: if the primary fails (auth error, rate limit, connection timeout), attempt fallback provider; if fallback is not configured or also fails, return error response with failure reason
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 7.5 Write unit tests for AIProviderManager
    - Test primary-to-fallback switch on rate-limit error
    - Test error response when both providers fail
    - Test 30-second initialization timeout triggers failure log
    - _Requirements: 3.3, 3.5, 3.6_

- [x] 8. Implement Skill base class and Manifest validator
  - [x] 8.1 Implement `Skill` abstract base class in `skills/base.py`
    - Define abstract properties `name` and `version`
    - Define abstract `execute(context: SkillContext) -> SkillResponse`
    - Provide default no-op implementations for all lifecycle hooks: `on_load`, `on_enable`, `on_disable`, `on_unload`
    - _Requirements: 1.6, 11.5_

  - [x] 8.2 Implement manifest validation in `skills/manifest.py`
    - Validate required fields: `name` (1–64 chars, alphanumeric/hyphen/underscore), `version` (semver), `description` (1–500 chars), `entry_point` (`module:ClassName` format), `intents` (≥1 intent, each with `intent_name`, `description`, ≥3 `example_utterances`)
    - Validate optional `permissions` against allowed values: `file_system`, `network`, `user_data`, `audio_input`, `audio_output`, `system_settings`
    - Raise descriptive validation errors for malformed JSON, missing fields, or format violations
    - _Requirements: 1.3, 1.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [ ]* 8.3 Write unit tests for Skill base class and manifest validation
    - Test that a class not implementing `execute` cannot be instantiated
    - Test manifest validation accepts valid manifests and rejects each invalid field type with a descriptive error
    - _Requirements: 1.3, 1.4, 10.7_

- [x] 9. Implement Skill Registry
  - [x] 9.1 Implement `SkillRegistry` in `skills/registry.py`
    - Implement `discover_skills()`: scans the `skills/` directory for subdirectories containing `manifest.json`
    - Implement `load_skill()`: validates the manifest, dynamically imports the entry-point module, instantiates the skill class, calls `on_load()` lifecycle method, and makes intent patterns available to the router; log and skip on validation failure without affecting other skills
    - Implement `unload_skill()`: calls `on_unload()` and removes the skill
    - Implement `enable_skill()` / `disable_skill()`: call `on_enable()` / `on_disable()` lifecycle hooks; leave skill disabled if `on_enable` raises
    - Implement `get_skill()`, `get_enabled_skills()`, `get_all_intents()`
    - Support hot-reload: new skill directories discovered and registered within 5 seconds without platform restart
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.2, 11.1, 11.2, 11.3, 11.4, 11.6, 11.7, 11.8_

  - [ ]* 9.2 Write unit tests for SkillRegistry
    - Test a valid skill directory is discovered and loaded successfully
    - Test a skill with a missing manifest field is skipped without affecting other skills
    - Test `disable_skill()` removes the skill's intents from the router
    - Test lifecycle methods are called in correct order (load → enable → disable → unload)
    - _Requirements: 1.2, 1.3, 1.4, 11.1, 11.4_

- [x] 10. Implement Intent Router
  - [x] 10.1 Implement `IntentRouter` in `skills/router.py`
    - Implement `route()`: call `_classify_intent_with_ai()` using the AI provider; if AI does not respond within 3000 ms or returns an error, fall back to `_classify_intent_with_keywords()`
    - Implement `_classify_intent_with_ai()`: send utterance and available intent patterns to AI provider; return `(intent_name, confidence, entities)`
    - Implement `_classify_intent_with_keywords()`: keyword matching against `example_utterances`
    - Implement `_select_skill()`: choose skill with highest confidence ≥ 0.5; break ties by registration order; route to default `conversation` skill if no match
    - Routing must complete within 500 ms for utterances ≤ 100 characters (excluding AI call time)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 10.2 Write unit tests for IntentRouter
    - Test AI timeout triggers keyword fallback
    - Test utterance is routed to the highest-confidence skill
    - Test tie-breaking selects the first-registered skill
    - Test utterance with no match above 0.5 confidence routes to conversation skill
    - _Requirements: 2.3, 2.4, 2.6_

- [x] 11. Checkpoint — Skills and routing layer
  - Ensure all tests for tasks 6–10 pass. Ask the user if any questions arise before continuing.

- [x] 12. Implement Platform Core
  - [x] 12.1 Implement `Platform` class in `platform/core.py`
    - Implement `start()`: initialise `ConfigurationManager`, `PlatformLogger`, `ErrorHandler`, `MemoryManager`, `ContextManager`, `AIProviderManager`, `SkillRegistry`, `IntentRouter`, and `VoicePipeline` in dependency order
    - Implement `shutdown()`: call `on_unload()` on all loaded skills in reverse load order
    - Implement `process_utterance()`: fetch context → route utterance → invoke skill; catch skill exceptions and return a safe error response; update conversation history; return `PlatformResponse`
    - Preserve conversation state when a skill execution error occurs
    - _Requirements: 1.7, 1.8, 8.1, 8.7, 11.4_

  - [ ]* 12.2 Write integration tests for Platform.process_utterance
    - Test a successful end-to-end utterance returns a non-empty response with the correct skill name
    - Test a skill exception returns a safe error response without leaking internal details
    - Test conversation state is preserved after a skill error
    - _Requirements: 1.8, 8.1, 8.4, 8.7_

- [x] 13. Implement Voice Pipeline
  - [x] 13.1 Implement STT engine interfaces and concrete classes
    - Write `STTEngine` abstract base in `voice/stt/base.py` with abstract `transcribe()` and `is_available()`
    - Implement `GoogleSTTEngine` in `voice/stt/google.py`: wraps `SpeechRecognition` library; wait up to 5 s for speech, capture up to 15 s
    - Implement `WhisperSTTEngine` in `voice/stt/whisper.py`: wraps `openai-whisper`
    - Implement `WebSpeechSTTEngine` in `voice/stt/web_speech.py`: stub for browser JS bridge
    - _Requirements: 4.1, 4.3_

  - [x] 13.2 Implement TTS engine interfaces and concrete classes
    - Write `TTSEngine` abstract base in `voice/tts/base.py` with abstract `speak()`, `stop()`, `is_available()`, `configure()`
    - Implement `EdgeTTSEngine` in `voice/tts/edge_tts.py`: wraps `edge-tts` with `pygame` mixer (as in existing `VoiceEngine`)
    - Implement `Pyttsx3TTSEngine` in `voice/tts/pyttsx3.py`: wraps `pyttsx3`; auto-selects female voice; strips markdown before speaking
    - Implement `BrowserTTSEngine` in `voice/tts/browser.py`: stub that returns the JS injection string (from existing `get_voice_js()`)
    - _Requirements: 4.2, 4.4, 4.5_

  - [x] 13.3 Implement `VoicePipeline` in `voice/pipeline.py`
    - Implement `initialize()`: load configured STT and TTS engines from `ConfigurationManager`
    - Implement `set_stt_engine()` / `set_tts_engine()`: hot-swap engines without restart
    - Implement `listen()`: call STT engine; fall back to text-input mode with a notification on `unavailable microphone`, `network timeout`, or `speech recognition error`
    - Implement `speak()`: call TTS engine; fall back to text-only mode with a notification on `unavailable audio output`, `engine init error`, or `synthesis error`
    - Implement `configure_voice()` and `enable_voice()`
    - Support voice config: gender, language code, speech rate (50–300 wpm), volume (0.0–1.0)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 13.4 Write unit tests for VoicePipeline
    - Test STT failure triggers text-input fallback with notification message
    - Test TTS failure triggers text-only fallback with notification message
    - Test `set_stt_engine()` swaps engine without restarting the pipeline
    - _Requirements: 4.6, 4.7_

- [x] 14. Implement built-in skills
  - [x] 14.1 Create `skills/conversation/` skill
    - Write `manifest.json` with name `conversation-skill`, version `1.0.0`, description, entry point, and at least 3 example utterances for general-chat intent
    - Implement `ConversationSkill` in `skills/conversation/conversation.py` extending `Skill`
    - `execute()` passes the utterance and conversation history to the `AIProviderManager` and returns the generated text
    - _Requirements: 7.3, 7.5, 7.6_

  - [x] 14.2 Create `skills/weather/` skill
    - Write `manifest.json` with `network` permission and weather intent with ≥3 example utterances
    - Implement `WeatherSkill` in `skills/weather/weather.py`
    - `execute()` extracts a location entity, fetches current conditions (temperature, humidity, conditions description) and forecast summary from the weather API (wttr.in as in existing code)
    - If the weather service is unavailable, return a response indicating the weather service is temporarily unavailable
    - _Requirements: 7.1, 7.5, 7.6, 7.7_

  - [x] 14.3 Create `skills/news/` skill
    - Write `manifest.json` with `network` permission and news intent with ≥3 example utterances
    - Implement `NewsSkill` in `skills/news/news.py`
    - `execute()` fetches up to 5 headlines from the past 24 hours; each summary 1–2 sentences; uses `feedparser` as in the existing code
    - If the news service is unavailable, return a response indicating the news service is temporarily unavailable
    - _Requirements: 7.2, 7.5, 7.6, 7.8_

  - [x] 14.4 Create `skills/maps/` skill
    - Write `manifest.json` with `network` and `system_settings` permissions and maps intent with ≥3 example utterances
    - Implement `MapsSkill` in `skills/maps/maps.py`
    - `execute()` constructs a Google Maps URL for the location query and opens it in the default browser using `webbrowser.open()`
    - _Requirements: 7.4, 7.5, 7.6_

  - [ ]* 14.5 Write unit tests for built-in skills
    - Test `WeatherSkill` returns a fallback message when the weather API raises an exception
    - Test `NewsSkill` returns a fallback message when the news feed raises an exception
    - Test each skill's manifest passes validation
    - _Requirements: 7.6, 7.7, 7.8_

- [x] 15. Checkpoint — Platform core and skills
  - Ensure all tests for tasks 12–14 pass. Ask the user if any questions arise before continuing.

- [x] 16. Implement web interface
  - [x] 16.1 Extract and implement the JARVIS theme in `interfaces/web/theme.py`
    - Move all existing CSS from `app.py` into `get_jarvis_css()` helper
    - Verify JARVIS dark theme: cyan accent `#5ac8e8`, dark background `#040d18`, Share Tech Mono typography
    - _Requirements: 9.1_

  - [x] 16.2 Implement Streamlit web interface in `interfaces/web/app.py`
    - Instantiate `Platform` and call `platform.start()` once per session using `st.session_state`
    - Replace direct calls to `ask_meryna()` and `speak_text()` with `platform.process_utterance()` and `platform.get_voice_pipeline().speak()`
    - Use `WebSpeechSTTEngine` JS injection (from `BrowserTTSEngine.get_js()`) for browser microphone input
    - Display error message and allow text-input fallback if browser microphone access is denied
    - Preserve JARVIS chat UI: dark theme, cyan messages, pulsing orb, quick-action chips, sidebar settings
    - _Requirements: 9.1, 9.3, 9.5, 9.7, 9.8_

  - [x] 16.3 Update root `app.py` as a thin entry point
    - Import and run the new `interfaces/web/app.py` so `streamlit run app.py` continues to work
    - _Requirements: 9.1_

- [x] 17. Implement CLI interface
  - [x] 17.1 Implement CLI interface in `interfaces/cli/app.py`
    - Instantiate `Platform` and call `platform.start()`; call `platform.shutdown()` on exit
    - Use `GoogleSTTEngine` for desktop microphone input and `EdgeTTSEngine` for audio output (as in existing `Meryna.py`)
    - Display terminal error and terminate gracefully within 5 seconds if no working microphone is found
    - Implement the same greeting / quit / think loop currently in `Meryna.run()`
    - _Requirements: 9.2, 9.4, 9.6, 9.7, 9.8_

  - [x] 17.2 Create `cli.py` entry point
    - Import and run `interfaces/cli/app.py` so `python cli.py` starts the CLI
    - _Requirements: 9.2_

- [x] 18. Wire interfaces to shared memory and skill infrastructure
  - [x] 18.1 Verify shared memory file between web and CLI
    - Confirm both interfaces resolve memory storage to the same path (`~/.meryna_memory.json` by default)
    - Write integration test asserting that a conversation turn written by one interface is visible to the other after reload
    - _Requirements: 9.7, 9.8_

  - [ ]* 18.2 Write integration test for identical skill responses across interfaces
    - Invoke the same utterance via the platform's `process_utterance()` with web and CLI session IDs
    - Assert the `text` field of both `PlatformResponse` objects is identical
    - _Requirements: 9.7_

- [x] 19. Final checkpoint — Full platform
  - Run the full test suite and ensure all tests pass. Verify `streamlit run app.py` and `python cli.py` both start correctly. Ask the user if any questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP delivery
- Each task references specific requirements for traceability
- The existing `Meryna.py`, `app.py`, `meryna_brain.py`, and `meryna_voice.py` files remain intact until tasks 16–17 replace them; keep both working in parallel during migration
- Python is the implementation language throughout; all async methods use `asyncio`
- Checkpoints ensure incremental validation at each major layer boundary

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.2", "6.1", "7.1", "8.1"] },
    { "id": 3, "tasks": ["6.2", "7.2", "7.3", "8.2"] },
    { "id": 4, "tasks": ["6.3", "7.4", "8.3"] },
    { "id": 5, "tasks": ["7.5", "9.1", "10.1"] },
    { "id": 6, "tasks": ["9.2", "10.2", "12.1"] },
    { "id": 7, "tasks": ["12.2", "13.1", "13.2"] },
    { "id": 8, "tasks": ["13.3", "14.1", "14.2", "14.3", "14.4"] },
    { "id": 9, "tasks": ["13.4", "14.5"] },
    { "id": 10, "tasks": ["16.1", "17.1"] },
    { "id": 11, "tasks": ["16.2", "17.2"] },
    { "id": 12, "tasks": ["16.3", "18.1"] },
    { "id": 13, "tasks": ["18.2"] }
  ]
}
```
