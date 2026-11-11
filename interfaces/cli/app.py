"""
Meryna CLI interface.

A terminal front-end that shares the same :class:`~platform.core.Platform` as
the web interface.  It uses the desktop microphone (``GoogleSTTEngine``) for
input and Edge neural TTS (``EdgeTTSEngine``) for spoken output, mirroring the
greeting / quit / think loop of the legacy ``Meryna.run()``.

If no working microphone is found, it prints a terminal error and terminates
gracefully within 5 seconds (Requirement 9.6).

Requirements addressed: 9.2, 9.4, 9.6, 9.7, 9.8
"""

from __future__ import annotations

import asyncio
import itertools
import re
import sys

from meryna_platform.core import Platform
from voice.stt.base import STTEngineType
from voice.tts.base import TTSEngineType

_QUIT_WORDS = {"quit", "exit", "bye", "close session", "goodbye"}

_GREETING_RETURNING = "Hey! Meryna here. What's up?"
_GREETING_FIRST = "Hey! Meryna here. How can I help?"
_FAREWELL = "Bye. Just call me whenever."

# Wake phrases — if the user says only one of these (no actual question),
# Meryna gives a short "I'm listening" acknowledgement instead of treating it
# as a request.
_WAKE_WORDS = (
    "hey meryna",
    "hi meryna",
    "hello meryna",
    "ok meryna",
    "okay meryna",
    "meryna",
    "wake up",
    "wake up meryna",
    "you there",
    "are you there",
)

# Short acknowledgements, cycled so it doesn't say the same one every time.
_ACKNOWLEDGEMENTS = (
    "Hmm, tell me.",
    "Yeah, I'm listening.",
    "Hmm hmm, go ahead.",
    "Yes? I'm here.",
    "Mm, what's up?",
    "Right here. Go on.",
)
_ack_cycle = itertools.cycle(_ACKNOWLEDGEMENTS)


def _is_wake_only(text: str) -> bool:
    """Return ``True`` if *text* is just a wake phrase with no real request.

    e.g. "hey meryna" → True (needs an acknowledgement), but
    "hey meryna what's the weather" → False (process it as a question).
    """
    # Normalise: lowercase, drop punctuation, collapse whitespace.
    normalised = re.sub(r"[^\w\s]", "", text.lower()).strip()
    normalised = re.sub(r"\s+", " ", normalised)
    return normalised in _WAKE_WORDS


def _print_meryna(text: str) -> None:
    print(f"\n  [Meryna] {text}", flush=True)


def _print_you(text: str) -> None:
    print(f"  [You] {text}", flush=True)


async def _speak(platform: Platform, text: str) -> None:
    """Speak *text* through the voice pipeline, ignoring audio failures."""
    voice = platform.get_voice_pipeline()
    if voice is None:
        return
    try:
        await voice.speak(text)
    except Exception:  # noqa: BLE001
        pass


async def _speak_interruptible(platform: Platform, text: str, voice_mode: bool):
    """Speak *text*; if the user talks over it (voice mode), return their words.

    Returns the barge-in transcript (str) when the user interrupts, else
    ``None`` once playback finishes normally.
    """
    voice = platform.get_voice_pipeline()
    if voice is None:
        return None
    # Only attempt barge-in in voice mode; otherwise just speak normally.
    if not voice_mode:
        await _speak(platform, text)
        return None
    try:
        result = await voice.speak_interruptible(text)
    except Exception:  # noqa: BLE001
        return None
    if result.ok and result.text:
        _print_you(result.text)
        return result.text
    return None


async def run_cli(voice_mode: bool = True) -> int:
    """Run the interactive CLI loop.  Returns a process exit code."""
    platform = Platform()
    print("=== MERYNA — VOICE ASSISTANT (CLI) ===", flush=True)
    print("  Booting platform...", flush=True)
    await platform.start()

    voice = platform.get_voice_pipeline()

    # Prefer desktop STT/TTS engines for the CLI.
    if voice is not None:
        voice.set_stt_engine(STTEngineType.GOOGLE)
        voice.set_tts_engine(TTSEngineType.EDGE_TTS)

    stt = voice.get_stt_engine() if voice else None
    mic_ok = bool(stt and stt.is_available())

    if voice_mode and not mic_ok:
        print(
            "\n  [!] No working microphone was found. "
            "Switching to text-only mode.",
            flush=True,
        )
        voice_mode = False

    # Greeting.
    greeting = _GREETING_FIRST
    _print_meryna(greeting)
    await _speak(platform, greeting)

    if voice_mode:
        print(
            "  (Tip: just start talking any time to interrupt Meryna.)",
            flush=True,
        )

    # Words captured by interrupting Meryna become the next turn's input.
    pending_input = None

    try:
        while True:
            if pending_input is not None:
                user_input, pending_input = pending_input, None
            else:
                user_input = await _get_input(platform, voice_mode)
            if not user_input:
                continue

            if user_input.strip().lower() in _QUIT_WORDS:
                _print_meryna(_FAREWELL)
                await _speak(platform, _FAREWELL)
                break

            # Bare wake word ("hey meryna") — just acknowledge and listen,
            # rather than sending it to the AI as a question.
            if _is_wake_only(user_input):
                ack = next(_ack_cycle)
                _print_meryna(ack)
                pending_input = await _speak_interruptible(
                    platform, ack, voice_mode
                )
                continue

            print("  Meryna is thinking...", flush=True)
            response = await platform.process_utterance(
                user_input, session_id="cli"
            )
            _print_meryna(response.text)
            # Speak the reply; if the user talks over it, capture what they said
            # and feed it straight into the next loop iteration (barge-in).
            pending_input = await _speak_interruptible(
                platform, response.text, voice_mode
            )
    except (KeyboardInterrupt, EOFError):
        print("\n  Interrupted.", flush=True)
    finally:
        await platform.shutdown()

    return 0


async def _get_input(platform: Platform, voice_mode: bool):
    """Get one utterance from the microphone (voice mode) or the keyboard."""
    if voice_mode:
        print("\n  >>> LISTENING... speak now <<<", flush=True)
        voice = platform.get_voice_pipeline()
        result = await voice.listen()
        if result.notification:
            print(f"  [{result.notification}]", flush=True)
        if result.ok and result.text:
            _print_you(result.text)
            return result.text
        if result.fell_back:
            # Microphone became unavailable — fall through to text input.
            return await asyncio.to_thread(_read_line)
        return None

    return await asyncio.to_thread(_read_line)


def _read_line():
    """Blocking keyboard read (run in a thread)."""
    try:
        sys.stdout.write("\n  You --> ")
        sys.stdout.flush()
        return input().strip() or None
    except (EOFError, KeyboardInterrupt):
        return "quit"


def main() -> None:
    """Entry point for ``python cli.py``."""
    voice_mode = "--text" not in sys.argv
    try:
        exit_code = asyncio.run(run_cli(voice_mode=voice_mode))
    except KeyboardInterrupt:
        exit_code = 0
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
