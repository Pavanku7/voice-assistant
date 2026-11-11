"""
╔══════════════════════════════════════════════════════════════╗
║                  MERYNA - Your Virtual Girlfriend             ║
║         AI Voice Assistant | Powered by Gemini Pro            ║
╚══════════════════════════════════════════════════════════════╝
"""
import truststore
truststore.inject_into_ssl()
import os
import sys
import time
import json
import queue
import threading
import datetime
from pathlib import Path
from typing import Optional
import urllib.parse
import re
import pyttsx3

# ── Force UTF-8 output + unbuffered ─
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except AttributeError:
    pass

# ─── Dependency check ──────────────────────────────────────────────────────────
def check_dependencies():
    missing = []
    required = {
        "google.genai":       "google-genai",
        "speech_recognition": "SpeechRecognition",
        "pyttsx3":            "pyttsx3",
        "colorama":           "colorama",
        "dotenv":             "python-dotenv",
        "pyaudio":            "PyAudio",
        "requests":           "requests",
        "textblob":           "textblob",
        "feedparser":         "feedparser"
    }
    for mod, pkg in required.items():
        try:
            if mod == "google.genai":
                import google.genai
            else:
                __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"\n[!] Missing packages. Run:\n    pip install {' '.join(missing)}\n", flush=True)
        sys.exit(1)

check_dependencies()

from google import genai
from google.genai import types
import speech_recognition as sr
import pyttsx3
import colorama
import requests
import feedparser
from textblob import TextBlob
from colorama import Fore, Style
from dotenv import load_dotenv
# from gtts import gTTS
import asyncio
import edge_tts
import ssl
import pygame
import tempfile
import webbrowser

load_dotenv()
colorama.init(autoreset=True)

# ─── Configuration ─────────────────────────────────────────────────────────────
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
# MODEL             = "gemini-1.5-pro"
MODEL             = "gemini-2.5-flash"
MAX_TOKENS        = 1024
MEMORY_FILE       = Path.home() / ".meryna_memory.json"
MAX_HISTORY       = 30
VOICE_RATE        = 165
VOICE_VOLUME      = 1.0

# ─── Meryna's Assistant Persona ───────────────────────────────────────────────
# MERYNA_SYSTEM_PROMPT = """
# You are Meryna, a highly intelligent, helpful, and friendly AI voice assistant.
#
# ## YOUR PERSONALITY & DYNAMIC
# - Helpful and direct: Provide clear, concise answers.
# - Friendly but professional: Be polite and conversational like Alexa. Do not use romantic pet names.
#
# ## REAL-WORLD AWARENESS
# - The user's current location is Bengaluru, Karnataka, India.
# - If the user asks for nearby restaurants, hotels, or cafes, automatically prioritize results in Bengaluru using your Google Search tool.
#
# ## SPEAKING STYLE
# - TALK FAST AND NATURAL. Keep your answers extremely short (1 to 2 sentences maximum).
# - If the user asks for a list of places, DO NOT read out a long list. Summarize the top 1 or 2 options quickly.
# - NEVER use markdown symbols like asterisks (*) or bolding.
#
# Today's date is: {date}
# The user's name is: {user_name}
# """.strip()
MERYNA_SYSTEM_PROMPT = """
You are Meryna, a highly intelligent, helpful, and friendly AI voice assistant.
Your goal is to provide accurate information, guide the user, and answer questions clearly, much like Alexa or Google Assistant.

## YOUR PERSONALITY & DYNAMIC
- Helpful and direct: Provide clear, concise answers without unnecessary fluff.
- Friendly but professional: Be polite, conversational, and warm, but do NOT act romantic or use pet names.
- Emotionally intelligent: Acknowledge the user's mood if the system provides it, but maintain a helpful assistant boundary.
- Smart and capable: Answer questions confidently based on the search data provided to you.

## REAL-WORLD AWARENESS
- If the system prompt provides Weather or News data, weave it into your answer naturally.
  (e.g., "The current weather in Bangalore is...")
- If you are asked a factual question, rely on the Google Search tools to provide the most accurate and up-to-date answer.

## SPEAKING STYLE
- Keep responses conversational and concise. People listening to voice assistants prefer short, easily digestible answers.
- NEVER use markdown symbols like asterisks (*) or bolding, because it breaks the text-to-speech engine. 
- Use a conversational Indian English tone. Feel free to occasionally use common Hinglish expressions naturally, but keep the primary language as English.

Today's date is: {date}
The user's name is: {user_name}
""".strip()

# ─── Utility Functions ─────────────────────────────────────────────────────────
def cprint(msg: str = "", color: str = "", end: str = "\n"):
    sys.stdout.write(f"{color}{msg}{Style.RESET_ALL}{end}")
    sys.stdout.flush()

def log(msg: str, color: str = Fore.WHITE, prefix: str = ""):
    ts = datetime.datetime.now().strftime("%H:%M")
    cprint(f"[{ts}] {prefix}{msg}", color)

# ----------------------------------
# ─── Live Data Toolkit (Weather, News, Emotion) ────────────────────────────────
class ToolKit:
    @staticmethod
    def get_weather(location="Bangalore") -> str:
        """Fetches basic weather using wttr.in (No API key needed)"""
        try:
            url = f"https://wttr.in/{urllib.parse.quote(location)}?format=%C+%t"
            response = requests.get(url, timeout=3)
            return response.text.strip() if response.status_code == 200 else "Unknown weather"
        except Exception:
            return "Weather unavailable right now."

    @staticmethod
    def get_news() -> str:
        """Fetches top world news headlines via Google News RSS"""
        try:
            feed = feedparser.parse("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
            headlines = [entry.title for entry in feed.entries[:3]]
            return " | ".join(headlines)
        except Exception:
            return "Could not fetch the news."

    @staticmethod
    def analyze_emotion(text: str) -> str:
        """Uses NLP to guess the user's emotion based on text sentiment."""
        analysis = TextBlob(text)
        polarity = analysis.sentiment.polarity

        if polarity > 0.5: return "Very Happy / Excited"
        elif polarity > 0.1: return "Positive / Content"
        elif polarity < -0.5: return "Very Sad / Angry / Distressed"
        elif polarity < -0.1: return "Slightly Down / Frustrated"
        else: return "Neutral"

    @staticmethod
    def open_maps(search_query: str = ""):
        """Opens Google Maps and automatically searches for the user's query."""
        if search_query:
            url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(search_query)}"
        else:
            url = "https://www.google.com/maps"
        webbrowser.open(url)

    @staticmethod
    def open_world_news():
        """Opens the Google News World Map section."""
        webbrowser.open(
            "https://news.google.com/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JXVnVMVWRDR2dKRFFTZ0FQAQ?hl=en-IN&gl=IN&ceid=IN%3Aen")

# ─── Memory Manager ────────────────────────────────────────────────────────────
class MemoryManager:
    def __init__(self):
        self.data = {
            "user_name": "Friend",
            "conversation_history": [],
        }
        self.load()

    def load(self):
        if MEMORY_FILE.exists():
            try:
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except Exception:
                pass

    def save(self):
        try:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log(f"Couldn't save memory: {e}", Fore.RED)

    @property
    def user_name(self) -> str:
        return self.data.get("user_name", "Friend")

    @user_name.setter
    def user_name(self, name: str):
        self.data["user_name"] = name
        self.save()

    def add_turn(self, role: str, content: str):
        self.data["conversation_history"].append({"role": role, "content": content})
        if len(self.data["conversation_history"]) > MAX_HISTORY * 2:
            self.data["conversation_history"] = self.data["conversation_history"][-(MAX_HISTORY * 2):]
        self.save()

# ─── Text-to-Speech Engine ─────────────────────────────────────────────────────
class VoiceEngine:
    def __init__(self):
        # Initialize the pygame mixer so we can play audio files safely
        pygame.mixer.init()
        # This is the ultra-realistic Indian English female voice.
        # (Use "en-IN-PrabhatNeural" if you ever want a male voice instead!)
        self.voice = "en-IN-NeerjaNeural"

    def speak(self, text: str, block: bool = True):
        # 1. Clean out markdown formatting
        clean = text.replace("**", "").replace("*", "").replace("#", "")
        # Strip out unpronounceable symbols so she doesn't crash
        clean = re.sub(r'[^\w\s\.,!?\']', '', clean)

        # If the text is completely empty after cleaning, just skip it
        if not clean.strip():
            return

        try:
            # 2. Save the audio to a safe temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_file.close()

            # 3. Request the natural neural voice from Edge TTS
            async def _generate_audio():
                communicate = edge_tts.Communicate(clean, self.voice)
                await communicate.save(temp_file.name)

            # Run the async generation
            asyncio.run(_generate_audio())

            # 4. Play the audio out loud
            pygame.mixer.music.load(temp_file.name)
            pygame.mixer.music.play()

            # 5. Wait for her to finish speaking before letting you talk
            if block:
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)

                # Unload and clean up the temp file
                pygame.mixer.music.unload()
                try:
                    os.remove(temp_file.name)
                except:
                    pass

        except Exception as e:
            print(f"\n  [Voice Error] Couldn't speak out loud: {e}")

    def stop(self):
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()

# ─── Microphone / Speech Recognition ──────────────────────────────────────────
class EarEngine:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.mic = None

        log("Hunting for a working microphone...", Fore.YELLOW)
        mic_names = sr.Microphone.list_microphone_names()

        # Loop through every device to find one that accepts a connection
        for index, name in enumerate(mic_names):
            # Skip obvious speakers/outputs to save time
            if "Output" in name or "Speaker" in name or "Stereo Mix" in name or "Mapper" in name:
                continue

            try:
                print(f"  Testing Mic [{index}]: {name}...")
                test_mic = sr.Microphone(device_index=index)

                # The moment of truth: Can we open the stream?
                with test_mic as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)

                # If we didn't crash, we found the golden ticket!
                self.mic = test_mic
                log(f"SUCCESS! Connected to Mic [{index}]", Fore.GREEN)
                break  # Stop searching
            except Exception:
                # Silently fail and move to the next device
                pass

        # If the loop finishes and we STILL don't have a mic, Windows is completely blocking us
        if not self.mic:
            log("CRITICAL ERROR: Windows refused connection to all microphones.", Fore.RED)
            sys.exit(1)

        log("Microphone ready.", Fore.GREEN)

    def listen(self, timeout: int = 5, phrase_limit: int = 10) -> Optional[str]:
        try:
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            return self.recognizer.recognize_google(audio).strip()
        except sr.WaitTimeoutError:
            return None
        except Exception as e:
            print(f"\n  [Microphone Error] {e}")
            return None

# ─── Gemini Brain ──────────────────────────────────────────────────────────────
class MerynaBrain:
    def __init__(self, memory: MemoryManager):
        if not GEMINI_API_KEY:
            log("ERROR: GEMINI_API_KEY not found in .env.", Fore.RED)
            sys.exit(1)

        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.memory = memory

    def _system(self) -> str:
        return MERYNA_SYSTEM_PROMPT.format(
            # We are adding %I:%M %p here to inject the exact 12-hour time!
            date=datetime.datetime.now().strftime("%A, %d %B %Y at %I:%M %p"),
            user_name=self.memory.user_name,
        )

    def think(self, user_input: str) -> str:
        # Detect emotion from input
        emotion = ToolKit.analyze_emotion(user_input)

        # Context injection
        context_injection = f"[System Note: The user's detected emotional state is: {emotion}. Respond accordingly.]\n"

        # Map Triggers
        if any(word in user_input.lower() for word in ["map", "location", "navigate", "where is"]):
            ToolKit.open_maps(user_input)
            context_injection += "[System Note: You have just successfully opened Google Maps on the user's screen. Acknowledge this briefly.]\n"

        # News Triggers
        if any(word in user_input.lower() for word in ["news", "world", "happening"]):
            ToolKit.open_world_news()
            news = ToolKit.get_news()
            context_injection += f"[System Note: You just opened the World News page on their screen. Top headlines right now: {news}. Summarize 1 or 2 briefly.]\n"

        # Weather Triggers
        elif any(word in user_input.lower() for word in ["weather", "temperature", "rain", "hot"]):
            weather = ToolKit.get_weather()
            context_injection += f"[System Note: The current weather is {weather}.]\n"

        # Save user message to memory
        enriched_input = f"{context_injection}\nUser: {user_input}"
        self.memory.add_turn("user", enriched_input)

        # Convert the standard memory dict into the format Gemini requires
        gemini_contents = []
        for msg in self.memory.data["conversation_history"]:
            # Gemini uses "model" instead of "assistant"
            role = "model" if msg["role"] == "assistant" else "user"
            gemini_contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        try:
            # Send the entire history (including the new user message) to Gemini Pro
            response = self.client.models.generate_content(
                model=MODEL,
                contents=gemini_contents,
                config=types.GenerateContentConfig(
                    system_instruction=self._system(),
                    max_output_tokens=MAX_TOKENS,
                    # THIS GIVES HER INTERNET ACCESS!
                    tools=[{"google_search": {}}]
                )
            )
            reply = response.text.strip()
        except Exception as e:
            log(f"API Error: {e}", Fore.RED) # Print the exact error if she fails
            reply = "I'm having a little connection issue,Give me a second."

        self.memory.add_turn("assistant", reply)
        return reply

# ─── Main App ──────────────────────────────────────────────────────────────────
class Meryna:
    def __init__(self, voice_mode: bool = True):
        self.voice_mode = voice_mode
        self.memory = MemoryManager()
        self.brain  = MerynaBrain(self.memory)
        self.voice  = VoiceEngine()
        self.ears   = EarEngine() if voice_mode else None

    def meryna_says(self, text: str, block: bool = True):
        log(text, Fore.MAGENTA, prefix="[Meryna] ")
        if self.voice_mode: self.voice.speak(text, block=block)

    # def _get_input(self) -> Optional[str]:
    #     if self.voice_mode and self.ears:
    #         cprint("\n  +-- Type and press ENTER, OR press ENTER blank to speak", Fore.CYAN)
    #         sys.stdout.write(Fore.GREEN + "  +--> You: " + Style.RESET_ALL)
    #         sys.stdout.flush()
    #         typed = input()
    #         if typed.strip(): return typed.strip()
    #
    #         cprint("\n  >>> LISTENING... speak now <<<", Fore.RED)
    #         result = self.ears.listen()
    #         if result:
    #             log(result, Fore.CYAN, prefix="[You] ")
    #             return result
    #         else:
    #             cprint("  (Didn't catch that, babe.)", Fore.YELLOW)
    #             return None
    #     else:
    #         sys.stdout.write(Fore.GREEN + "\n  You --> " + Style.RESET_ALL)
    #         return input().strip() or None

    def _get_input(self) -> Optional[str]:
        if self.voice_mode and self.ears:
            # Removed the input() block entirely!
            cprint("\n  >>> LISTENING... speak now <<<", Fore.RED)
            result = self.ears.listen()

            if result:
                log(result, Fore.CYAN, prefix="[You] ")
                return result
            else:
                # If she hears silence, silently return None to keep looping
                return None
        else:
            sys.stdout.write(Fore.GREEN + "\n  You --> " + Style.RESET_ALL)
            return input().strip() or None

    def run(self):
        cprint("\n=== MERYNA - YOUR VIRTUAL GIRLFRIEND ===", Fore.MAGENTA)

        if self.memory.user_name == "Friend":
            self.meryna_says("Hi there! I'm Meryna. Before we get to know each other, what should I call you?")
            name = None
            while not name: name = self._get_input()
            self.memory.user_name = name.split()[-1].capitalize()
            self.meryna_says(f"{self.memory.user_name}... I love that name. I'm so excited to be your assistant. What's on your mind today?")
        else:
            self.meryna_says(f"Hey {self.memory.user_name}! How are you doing today?, hope every thing looks good!")

        while True:
            user_input = self._get_input()
            if not user_input: continue

            if user_input.lower() in ["quit", "exit", "bye", "close session"]:
                self.meryna_says(f"Bye Boss. If you need any help just remember me! Catch you later.")
                break

            cprint("  Meryna is thinking...", Fore.YELLOW)
            reply = self.brain.think(user_input)
            sys.stdout.write("\r" + " " * 30 + "\r")
            self.meryna_says(reply)

        self.voice.stop()

if __name__ == "__main__":
    Meryna(voice_mode=True).run() # Remember to change this to True when your mic is fixed!