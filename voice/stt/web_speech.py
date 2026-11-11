"""
WebSpeechSTTEngine — browser Web Speech API bridge (stub).

Server-side Python cannot capture the browser microphone directly; speech
recognition happens in the browser via the Web Speech API and the transcript
is delivered back through the Streamlit text input.  This engine therefore
exposes the JavaScript that must be injected into the page and treats
``transcribe`` as a no-op on the server.

Requirements addressed: 4.1, 4.3, 9.3, 9.5
"""

from __future__ import annotations

from typing import Optional

from voice.stt.base import STTEngine


class WebSpeechSTTEngine(STTEngine):
    """Browser Web Speech API STT engine (JS bridge stub).

    Parameters
    ----------
    language:
        BCP-47 language code used by the browser recogniser (default
        ``"en-IN"``).
    """

    def __init__(self, language: str = "en-IN") -> None:
        self._language = language

    def is_available(self) -> bool:
        """Availability is determined client-side; always ``True`` here.

        The browser decides at runtime whether the Web Speech API and mic
        permissions are present; the web interface handles that fallback.
        """
        return True

    async def transcribe(
        self,
        timeout: int = 5,
        max_duration: int = 15,
    ) -> Optional[str]:
        """No server-side transcription — handled by the browser.

        Returns ``None`` so the Voice Pipeline routes web input through the
        text box populated by the injected JavaScript.
        """
        return None

    # ------------------------------------------------------------------
    # Browser bridge
    # ------------------------------------------------------------------

    def get_js(self) -> str:
        """Return the JavaScript that wires the browser mic into Streamlit.

        Mirrors the legacy ``meryna_voice.get_voice_js`` implementation, with
        the language substituted from configuration.
        """
        return _WEB_SPEECH_JS.replace("__LANG__", self._language)


_WEB_SPEECH_JS = """
    <script>
    function initVoice() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            console.warn('Meryna Voice: SpeechRecognition not supported. Use Chrome or Edge.');
            return;
        }

        const recognition = new SR();
        recognition.continuous  = false;
        recognition.interimResults = true;
        recognition.lang        = '__LANG__';

        let listening = false;

        function getInput() {
            return parent.document.querySelector('input[data-testid="stTextInput-Input"]')
                || parent.document.querySelector('.stTextInput input');
        }

        function getMicBtn() {
            return parent.document.querySelector('button[title="Click to speak"]')
                   || [...parent.document.querySelectorAll('button')].find(b => b.innerText.includes('\\uD83C\\uDF99'));
        }

        recognition.onstart = () => {
            listening = true;
            const btn = getMicBtn();
            if (btn) { btn.style.background = '#2a0808'; btn.style.borderColor = '#e05a5a'; }
        };

        recognition.onresult = (event) => {
            const transcript = Array.from(event.results)
                .map(r => r[0].transcript).join('');

            const inp = getInput();
            if (inp) {
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(inp, transcript);
                inp.dispatchEvent(new Event('input', { bubbles: true }));
            }

            if (event.results[event.results.length - 1].isFinal) {
                recognition.stop();
                setTimeout(() => {
                    const inp2 = getInput();
                    if (inp2) {
                        inp2.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                        inp2.dispatchEvent(new KeyboardEvent('keyup',  { key: 'Enter', bubbles: true }));
                    }
                }, 400);
            }
        };

        recognition.onerror = (e) => {
            console.warn('Meryna Voice error:', e.error);
            const btn = getMicBtn();
            if (btn) { btn.style.background = ''; btn.style.borderColor = ''; }
            listening = false;
        };

        recognition.onend = () => {
            listening = false;
            const btn = getMicBtn();
            if (btn) { btn.style.background = ''; btn.style.borderColor = ''; }
        };

        const observer = new MutationObserver(() => {
            const btn = getMicBtn();
            if (btn && !btn._merynaBound) {
                btn._merynaBound = true;
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (listening) { recognition.stop(); }
                    else           { recognition.start(); }
                });
            }
        });

        observer.observe(parent.document.body, { childList: true, subtree: true });
    }

    setTimeout(initVoice, 1200);
    </script>
    """
