# MERYNA — Voice Assistant Platform

A JARVIS-inspired, voice-first AI assistant with an Alexa-style **plugin skill**
architecture. Meryna runs on a swappable AI backend (Google **Gemini** primary,
Anthropic **Claude** fallback) and a swappable voice pipeline, and ships with a
web UI and a terminal CLI that share the same core platform.

---

## 🚀 Quick Start

### Step 1 — Install Python dependencies
```bash
pip install -r requirements.txt
```

> **Windows note for pyaudio:** if `pip install pyaudio` fails, run:
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```
> PyAudio is only needed for **desktop microphone** input (the CLI voice mode).
> The web UI uses your browser's mic and does not require it.

### Step 2 — Add your API key(s)
Open `.env` in the project root and set at least the Gemini key:
```
GEMINI_API_KEY=your-gemini-key-here
ANTHROPIC_API_KEY=your-anthropic-key-here   # optional fallback
```
- Get a Gemini key: https://aistudio.google.com/apikey
- Get an Anthropic key: https://console.anthropic.com

> Gemini is the **primary** provider. Claude is an **optional fallback** used
> automatically if Gemini fails. If you only have a Gemini key, Meryna works
> fully — it just skips the fallback.

### Step 3 — Run Meryna

**Web UI (recommended):**
```bash
streamlit run app.py
```
Opens in your browser at **http://localhost:8501**.

**Terminal CLI:**
```bash
python cli.py            # voice mode (uses desktop mic + speaker)
python cli.py --text     # text-only mode (type to chat, no mic needed)
```

---

## 🗣️ How to Start a Conversation

### In the Web UI
1. Run `streamlit run app.py` and open http://localhost:8501.
2. Meryna greets you when the platform finishes booting.
3. **Type** a message in the input box and press Enter, **or** click the 🎙️
   mic button and speak (Chrome/Edge).
4. Meryna replies in text and speaks the response aloud.
5. Ask anything — e.g. *"What's the weather in Bengaluru?"*, *"Give me the
   latest news"*, or just chat.

### In the CLI
1. Run `python cli.py` (voice) or `python cli.py --text` (typing).
2. Wait for the boot line and greeting.
3. In voice mode, speak when you see `>>> LISTENING... speak now <<<`.
   In text mode, type at the `You -->` prompt.
4. Meryna thinks, prints, and speaks the reply.
5. To exit, say or type **quit**, **exit**, **bye**, or **goodbye**.

> If no working microphone is found, the CLI automatically drops to text-only
> mode so you can keep chatting.

---

## 🌐 Languages — English, Hindi & Nepali (automatic)

Meryna understands and replies in **English, Hindi, and Nepali**, and it picks
the language **automatically** — there's no setting to change. Speak or type in
any of the three and Meryna answers in the same language, in a matching neural
voice (Neerja for English, Swara for Hindi, Hemkala for Nepali). Ask in Hindi,
get a Hindi answer spoken in a Hindi voice; switch to Nepali mid-chat and it
follows.

## 🧩 What Meryna Can Do (built-in skills)

Meryna ships with 18 skills. Requests are routed to the right one automatically
by an AI intent classifier, with a keyword fallback if the AI is unavailable.

**Learning & kids (ages 6–15 friendly)**

| Skill | Try saying |
|---|---|
| **Homework Helper** | *"Explain the water cycle for my science homework"* — safe, simple, age-appropriate; searches the web for facts |
| **Web Search** | *"Search the web for the tallest mountain"* — answers factual questions (DuckDuckGo, no key) |
| **Dictionary** | *"What does 'resilient' mean?"* — meaning, spelling, examples |
| **Math Solver** | *"What is 15 percent of 200?"* — instant, exact calculations & word problems |
| **Translator** | *"How do you say thank you in Nepali?"* — translate between languages |
| **Wikipedia** | *"Tell me about Mount Everest"* — short encyclopedia summaries |
| **Stories** | *"Tell me a bedtime story about the moon"* — gentle, child-safe tales |

**Everyday utility**

| Skill | Try saying |
|---|---|
| **Date & Time** | *"What time is it?"*, *"What's today's date?"* — offline |
| **Converter** | *"Convert 10 km to miles"*, *"50 USD in INR"* — units + live currency |
| **Notes & To-do** | *"Add milk to my to-do list"*, *"read my notes"* — saved between sessions |
| **Reminders** | *"Remind me to take my medicine at 8 pm"* — saved; tells you what's due |

**Information, fun & wellbeing**

| Skill | Try saying |
|---|---|
| **Location** | *"Where am I right now?"* — auto-detects your location + local weather |
| **Weather** | *"What's the weather in Mumbai?"* — live conditions via wttr.in |
| **News** | *"What's the latest news?"* — headlines via Google News RSS |
| **Maps** | *"How do I get to the airport?"* — directions & places |
| **Fun** | *"Tell me a joke"*, *"Tell me a fun fact"* — clean, family-friendly |
| **Support** | *"I feel really down"* — calm, caring replies + trusted helpline info |
| **Conversation** | *"How are you today?"* — general chat, Q&A, advice (the fallback) |

> **Kids & safety notes.** The Homework Helper, Stories, and Fun skills are
> written to keep content age-appropriate for children via strong AI safety
> instructions (not a hard content filter). The **Support** skill detects
> crisis phrases and responds with a fixed, reviewed message containing India
> helpline numbers (KIRAN 1800-599-0019, Tele-MANAS 14416) — this pathway does
> **not** depend on the AI or network. Update those numbers for your region in
> `skills/support/support.py`.
>
> **Reminders** are saved and reported on request; Meryna has no always-on
> background timer, so it does not pop up an alert on its own — ask *"what's
> due?"* and it tells you.

**Adding your own skills is easy** — each skill is a self-contained folder, and
no core files need editing. Run `python new_skill.py <name>` to scaffold one, or
see [SKILLS.md](SKILLS.md) for the full guide.

---

## 📁 Project Structure
```
meryna/
├── app.py                  ← Web entry point (runs interfaces/web/app.py)
├── cli.py                  ← CLI entry point (runs interfaces/cli/app.py)
├── platform/               ← Core: orchestrator, config, logging, errors, models
│   └── core.py             ← Platform.process_utterance() — the shared entry point
├── ai/                     ← AI providers: Gemini (primary) + Claude (fallback)
├── skills/                 ← Plugin skills (registry, router, manifest + skill dirs)
│   ├── conversation/  weather/  news/  maps/  location/
│   ├── homework_helper/  web_search/  dictionary/  math_solver/  translator/
│   ├── datetime_info/  converter/  notes/  reminders/
│   ├── wikipedia/  fun/  stories/  support/
│   ├── geolocation.py      ← shared helper (location) — a file, not a skill
│   ├── websearch.py        ← shared helper (DuckDuckGo search)
│   └── userstore.py        ← shared helper (notes/reminders persistence)
├── i18n.py                 ← language auto-detect (English/Hindi/Nepali) + voices
├── voice/                  ← Swappable STT + TTS engines
│   ├── stt/                ← Google, Whisper, WebSpeech
│   └── tts/                ← EdgeTTS, pyttsx3, browser
├── memory/                 ← Conversation memory + context manager
├── interfaces/
│   ├── web/                ← Streamlit UI (JARVIS theme)
│   └── cli/                ← Terminal interface
├── legacy/                 ← Original monolithic version (kept for reference)
├── requirements.txt
├── .env                    ← Your API keys
└── README.md               ← This file
```

---

## ⚙️ Configuration

On first run, Meryna writes `meryna_config.json` to your home directory with
sensible defaults (AI provider, voice engines, personality prompt). Edit that
file to change models, voices, or the personality, and restart.

Conversation memory is stored locally at `~/.meryna_memory.json` and persists
between sessions. Both the web and CLI interfaces share the same memory.

To change Meryna's personality, edit `DEFAULT_PERSONALITY_PROMPT` in
`platform/core.py` (or override `personality_prompt` in `meryna_config.json`).

---

## 🧠 How It Works
```
You (voice/text)
   → STT (if voice)  → text
   → Platform.process_utterance()
        → memory + context
        → intent router  → picks a skill
        → skill.execute() → uses AI provider (Gemini → Claude fallback)
   → response text
   → TTS  → you hear Meryna speak
```

---

## 📦 Requirements
- Python 3.9+ (developed on 3.13)
- Internet connection (Gemini/Claude APIs, weather, news)
- Chrome or Edge browser for web mic input
- A **Gemini** API key (required); an **Anthropic** key (optional fallback)

---

## 🗂️ Legacy Version
The original single-file version now lives in [legacy/](legacy/)
(`Meryna.py`, `meryna_brain.py`, `meryna_voice.py`). It is **not** used by the
current platform and is kept only for reference.
