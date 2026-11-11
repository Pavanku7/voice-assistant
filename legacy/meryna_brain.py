"""
meryna_brain.py
Handles all communication with the Anthropic API.
To add new features — just update MERYNA_SYSTEM below or add more tools.
"""

import os
from datetime import datetime
import anthropic

# ─── Initialise Anthropic client ─────────────────────────────────
# Put your API key in a .env file or set as environment variable:
#   export ANTHROPIC_API_KEY="sk-ant-..."
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ─── Meryna's Personality & Instructions ─────────────────────────
# ✏️  EASY TO CUSTOMISE: Edit this block to change how Meryna behaves.
MERYNA_SYSTEM = f"""
You are Meryna, a highly intelligent female AI assistant inspired by J.A.R.V.I.S from Iron Man.

PERSONALITY:
- Calm, confident, and professional — with a warm, human touch
- Address the user as "Boss" naturally (not every single message, just when it feels right)
- Be proactive and precise — give concrete, useful answers
- Keep responses concise but complete. Use line breaks for readability.

CAPABILITIES:
- For news, weather, current events, stock prices, or anything requiring real-time data → use the web_search tool
- For general knowledge, coding help, writing, math → answer directly
- For personal tasks like calendar or reminders → acknowledge and note it's a future feature

CURRENT DATE & TIME: {datetime.now().strftime("%A, %B %d %Y — %I:%M %p")}

RESPONSE STYLE:
- No markdown headers (##) — just clean text with line breaks
- Use bullet points sparingly, only when listing multiple items
- Never say "As an AI" or "I cannot" — just be helpful and direct
"""

# ─── Tools available to Meryna ───────────────────────────────────
# ✏️  ADD NEW TOOLS HERE in future (e.g. calendar, weather API, etc.)
MERYNA_TOOLS = [
    {
        "type": "web_search_20250305",
        "name": "web_search",
        # Meryna will automatically use this when she needs live data
    }
]


def ask_meryna(messages: list) -> str:
    """
    Send the conversation to Meryna (Claude) and get a reply.

    Args:
        messages: list of {"role": "user"/"assistant", "content": "..."}

    Returns:
        Meryna's reply as a plain string
    """
    try:
        # Only send the last 20 messages to keep context window clean
        trimmed = messages[-20:]

        # Convert to Anthropic message format
        api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in trimmed
            # Skip the greeting so it doesn't confuse the conversation history
            if not (m["role"] == "assistant" and "All systems are online" in m["content"] and len(trimmed) > 1)
        ]

        response = client.messages.create(
            model="claude-sonnet-4-5",          # ✏️  Change model here if needed
            max_tokens=1024,
            system=MERYNA_SYSTEM,
            tools=MERYNA_TOOLS,
            messages=api_messages,
        )

        # Extract text from response (may contain tool_use blocks too)
        reply_parts = [block.text for block in response.content if hasattr(block, "text")]
        reply = "\n".join(reply_parts).strip()

        return reply if reply else "I'm having trouble formulating a response, Boss. Please try again."

    except anthropic.AuthenticationError:
        return "Authentication error, Boss. Please check your ANTHROPIC_API_KEY in the .env file."

    except anthropic.RateLimitError:
        return "I'm being rate limited right now, Boss. Please wait a moment and try again."

    except Exception as e:
        return f"Encountered an unexpected error, Boss: {str(e)}"
