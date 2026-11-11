"""
meryna_voice.py
Handles:
  1. speak_text()  — Meryna's voice output (she speaks replies back)
  2. get_voice_js() — injects browser mic recognition into Streamlit
  3. listen_once()  — desktop microphone input via SpeechRecognition library
"""

import platform
import threading


# ═══════════════════════════════════════════════════════════════════
# 1. TEXT-TO-SPEECH  — Meryna speaks her replies
# ═══════════════════════════════════════════════════════════════════

def speak_text(text: str) -> None:
    """
    Make Meryna speak the given text using the system TTS engine.
    Runs in a background thread so it doesn't block the UI.

    ✏️  To change voice speed/volume, edit the properties below.
    """
    def _speak():
        try:
            import pyttsx3
            engine = pyttsx3.init()

            # ── Voice settings ──────────────────────────────────
            engine.setProperty("rate", 165)       # speed (words/min). Default ~200
            engine.setProperty("volume", 0.9)     # 0.0 to 1.0

            # Try to pick a female voice
            voices = engine.getProperty("voices")
            female_voice = None
            for voice in voices:
                name = voice.name.lower()
                if any(word in name for word in ["female", "woman", "zira", "samantha", "karen", "victoria", "hazel", "susan"]):
                    female_voice = voice
                    break

            if female_voice:
                engine.setProperty("voice", female_voice.id)
            elif len(voices) > 1:
                engine.setProperty("voice", voices[1].id)  # index 1 is often female on Windows

            # Clean text (remove markdown symbols before speaking)
            clean = text.replace("*", "").replace("_", "").replace("#", "").replace("`", "")
            engine.say(clean)
            engine.runAndWait()

        except ImportError:
            print("[Meryna Voice] pyttsx3 not installed. Run: pip install pyttsx3")
        except Exception as e:
            print(f"[Meryna Voice] TTS error: {e}")

    thread = threading.Thread(target=_speak, daemon=True)
    thread.start()


# ═══════════════════════════════════════════════════════════════════
# 2. BROWSER MIC (Web Speech API via JavaScript)
#    Injected into the Streamlit page — picks up spoken input
#    and fills the chat input box automatically.
# ═══════════════════════════════════════════════════════════════════

def get_voice_js() -> str:
    """
    Returns JavaScript that:
    - Activates when the 🎙 button is clicked
    - Uses the browser's SpeechRecognition API (works in Chrome/Edge)
    - Fills the Streamlit text input with the transcribed speech
    - Auto-submits after the user stops speaking

    ✏️  To change the language, update 'recognition.lang' below.
        Examples: 'en-US', 'en-IN', 'hi-IN', 'ta-IN'
    """
    return """
    <script>
    // Wait for Streamlit to fully load before attaching voice logic
    function initVoice() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            console.warn('Meryna Voice: SpeechRecognition not supported. Use Chrome or Edge.');
            return;
        }

        const recognition = new SR();
        recognition.continuous  = false;
        recognition.interimResults = true;
        recognition.lang        = 'en-IN';  // ✏️ Change language here

        let listening = false;

        // Find Streamlit's text input box
        function getInput() {
            return parent.document.querySelector('input[data-testid="stTextInput-Input"]')
                || parent.document.querySelector('.stTextInput input');
        }

        // Find the mic button (🎙) inside the Streamlit iframe
        function getMicBtn() {
            return parent.document.querySelector('button[title="Click to speak"]')
                   || [...parent.document.querySelectorAll('button')].find(b => b.innerText.includes('🎙'));
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
                // Simulate React controlled input change
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(inp, transcript);
                inp.dispatchEvent(new Event('input', { bubbles: true }));
            }

            // Auto-submit when speech is final
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

        // Attach click handler to 🎙 button using MutationObserver
        // (needed because Streamlit re-renders buttons dynamically)
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

    // Small delay to ensure Streamlit DOM is ready
    setTimeout(initVoice, 1200);
    </script>
    """


# ═══════════════════════════════════════════════════════════════════
# 3. DESKTOP MICROPHONE INPUT (optional, non-browser mode)
#    Use this if you're running Meryna as a desktop Python script
#    without the Streamlit web UI.
# ═══════════════════════════════════════════════════════════════════

def listen_once(timeout: int = 5) -> str:
    """
    Listen from the desktop microphone and return transcribed text.
    Uses Google's free speech recognition API (needs internet).

    ✏️  To use offline recognition, swap to:
        recognizer.recognize_sphinx(audio)   — needs pocketsphinx
        recognizer.recognize_whisper(audio)  — needs openai-whisper

    Args:
        timeout: seconds to wait for speech before giving up

    Returns:
        Transcribed string, or empty string on failure
    """
    try:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300      # ✏️  Lower = more sensitive mic
        recognizer.dynamic_energy_threshold = True

        with sr.Microphone() as source:
            print("[Meryna] Listening... speak now.")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=15)

        text = recognizer.recognize_google(audio, language="en-IN")  # ✏️  Change language
        print(f"[Meryna] Heard: {text}")
        return text

    except ImportError:
        print("[Meryna Voice] SpeechRecognition not installed. Run: pip install SpeechRecognition pyaudio")
        return ""
    except Exception as e:
        print(f"[Meryna Voice] Could not understand audio: {e}")
        return ""
