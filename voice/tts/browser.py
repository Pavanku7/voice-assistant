"""
BrowserTTSEngine — browser Web Speech synthesis bridge (stub).

Speech synthesis happens client-side via the browser ``speechSynthesis`` API.
Server-side ``speak`` is a no-op; :meth:`get_js` returns the JavaScript the web
interface injects to speak a given piece of text in the browser.

Requirements addressed: 4.2, 4.4, 4.5, 9.3
"""

from __future__ import annotations

import json
import logging

from meryna_platform.models import VoiceConfig
from voice.tts.base import TTSEngine

logger = logging.getLogger("meryna.voice.tts.browser")


class BrowserTTSEngine(TTSEngine):
    """Browser Web Speech API TTS engine (JS bridge stub)."""

    def __init__(self, config: VoiceConfig | None = None) -> None:
        self._config = config or VoiceConfig()

    def is_available(self) -> bool:
        """Availability is decided client-side; always ``True`` here."""
        return True

    def configure(self, config: VoiceConfig) -> None:
        self._config = config

    def stop(self) -> None:
        # Handled client-side; nothing to stop on the server.
        pass

    async def speak(self, text: str, block: bool = True) -> bool:
        """No server-side synthesis — the web interface injects :meth:`get_js`."""
        return False

    # ------------------------------------------------------------------
    # Browser bridge
    # ------------------------------------------------------------------

    def get_js(self, text: str = "") -> str:
        """Return JavaScript that speaks *text* via ``window.speechSynthesis``.

        Rate is derived from the configured words-per-minute (≈165 wpm maps to
        the browser's default rate of 1.0).
        """
        # Browser rate is a multiplier where 1.0 ≈ normal speaking pace.
        rate = max(0.1, min(10.0, self._config.speech_rate / 165.0))
        volume = max(0.0, min(1.0, self._config.volume))
        lang = self._config.language
        payload = json.dumps(text)

        return f"""
    <script>
    (function() {{
        try {{
            if (!('speechSynthesis' in window)) return;
            var text = {payload};
            if (!text) return;
            var utter = new SpeechSynthesisUtterance(text);
            utter.lang = {json.dumps(lang)};
            utter.rate = {rate};
            utter.volume = {volume};
            var voices = window.speechSynthesis.getVoices();
            var preferFemale = {json.dumps(self._config.gender == "female")};
            if (preferFemale) {{
                var female = voices.find(function(v) {{
                    var n = v.name.toLowerCase();
                    return n.includes('female') || n.includes('zira') || n.includes('samantha');
                }});
                if (female) utter.voice = female;
            }}
            window.speechSynthesis.cancel();
            window.speechSynthesis.speak(utter);
        }} catch (e) {{ console.warn('Meryna TTS error:', e); }}
    }})();
    </script>
    """
