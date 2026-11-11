"""
Meryna web interface (Streamlit) — Ultron-style HUD.

Instantiates the shared :class:`~meryna_platform.core.Platform` once per session
and routes every message through :meth:`Platform.process_utterance`, so the web
UI uses exactly the same skills, routing, memory, and AI infrastructure as the
CLI.  The interface is rendered as a full sci-fi heads-up display: a glowing
central orb flanked by corner-bracketed panels wired to live platform data.
Browser speech synthesis is driven by :class:`BrowserTTSEngine.get_js`.

Requirements addressed: 9.1, 9.3, 9.5, 9.7, 9.8
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import streamlit as st

from meryna_platform.core import Platform
from voice.tts.browser import BrowserTTSEngine
from interfaces.web.theme import (
    get_footer_html,
    get_jarvis_css,
    get_left_panel_html,
    get_orb_html,
    get_right_panel_html,
    get_top_bar_html,
)


# ---------------------------------------------------------------------------
# Event loop + platform bootstrap (once per session)
# ---------------------------------------------------------------------------


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop stored in the session."""
    loop = st.session_state.get("_loop")
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        st.session_state["_loop"] = loop
    return loop


def _run(coro):
    """Run *coro* on the session's event loop."""
    return _get_loop().run_until_complete(coro)


def _get_platform() -> Platform:
    """Instantiate and start the platform once per Streamlit session."""
    platform = st.session_state.get("_platform")
    if platform is None:
        platform = Platform()
        _run(platform.start())
        st.session_state["_platform"] = platform
    return platform


def _provider_info(platform: Platform):
    """Return ``(name, model, fallback_ready, online)`` for the active AI provider."""
    manager = platform.get_ai_provider()
    if manager is None:
        return "N/A", "N/A", False, False
    provider = manager.get_provider()
    if provider is None:
        return "N/A", "N/A", False, False
    name = type(provider).__name__.replace("Provider", "")
    model = getattr(provider, "_model", "") or ""
    return name, model, bool(getattr(manager, "has_fallback", False)), True


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Meryna — AI Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(get_jarvis_css(), unsafe_allow_html=True)

platform = _get_platform()
registry = platform.get_skill_registry()
skill_names = list(getattr(registry, "loaded_skill_names", []))

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.greeted = False

if "voice_enabled" not in st.session_state:
    st.session_state.voice_enabled = True

# ---------------------------------------------------------------------------
# Top status bar
# ---------------------------------------------------------------------------

prov_name, prov_model, fallback_ready, online = _provider_info(platform)
now = datetime.now()

st.markdown(
    get_top_bar_html(
        system_id="MERYNA-1 · ADAPTIVE INTELLIGENCE CORE",
        clock=now.strftime("%Y-%m-%d  %H:%M:%S"),
        online=online,
    ),
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Boot greeting (once)
# ---------------------------------------------------------------------------

if not st.session_state.greeted:
    greeting = (
        "Hello. I'm Meryna — your personal AI assistant. "
        "All systems are online. How can I assist you today?"
    )
    st.session_state.messages.append({"role": "assistant", "content": greeting})
    st.session_state.greeted = True

# ---------------------------------------------------------------------------
# HUD layout: left panel | centre (orb + chat) | right panel
# ---------------------------------------------------------------------------

user_turns = len([m for m in st.session_state.messages if m["role"] == "user"])
col_left, col_center, col_right = st.columns([1.1, 2.4, 1.1], gap="medium")

# ── Left panel — real system metrics + session link ──
with col_left:
    st.markdown(
        get_left_panel_html(
            status_ok=online,
            provider=prov_name,
            model=prov_model,
            fallback_ready=fallback_ready,
            skill_count=len(skill_names),
            session_id="web",
            turns=user_turns,
            voice_enabled=st.session_state.voice_enabled,
        ),
        unsafe_allow_html=True,
    )

# ── Right panel — live skill matrix ──
with col_right:
    st.markdown(get_right_panel_html(skill_names), unsafe_allow_html=True)

# ── Centre — orb, chat history, input ──
with col_center:
    is_fresh = user_turns == 0
    st.markdown(
        get_orb_html(
            greeting="hello." if is_fresh else "MERYNA",
            subtitle="SYSTEM ONLINE · AWAITING COMMAND"
            if is_fresh
            else "LISTENING",
            speaking=False,
        ),
        unsafe_allow_html=True,
    )

    # Chat history
    chat_html = '<div class="chat-wrap">'
    for msg in st.session_state.messages:
        if msg["role"] == "assistant":
            chat_html += (
                f'<div class="msg-meryna"><div class="msg-label">MERYNA</div>'
                f'{msg["content"]}</div>'
            )
        else:
            chat_html += f'<div class="msg-user">{msg["content"]}</div>'
    chat_html += "</div>"
    st.markdown(chat_html, unsafe_allow_html=True)

    # Quick action chips (until the first user message)
    if is_fresh:
        quick_actions = [
            "Latest news today",
            "Weather in Bengaluru",
            "Open maps for MG Road",
            "Tell me a joke",
        ]
        cols = st.columns(len(quick_actions))
        for i, action in enumerate(quick_actions):
            if cols[i].button(action, key=f"quick_{i}"):
                st.session_state.pending_input = action
                st.rerun()

    # Input row
    col_inp, col_mic, col_send = st.columns([7, 1, 1])
    with col_inp:
        user_input = st.text_input(
            label="",
            placeholder="Type or use mic to speak to Meryna...",
            key="chat_input",
            label_visibility="collapsed",
        )
    with col_mic:
        st.button("🎙", help="Click to speak (browser mic)", key="mic_btn")
    with col_send:
        send_clicked = st.button("→", help="Send message", key="send_btn")

# ---------------------------------------------------------------------------
# Bottom telemetry footer
# ---------------------------------------------------------------------------

st.markdown(
    get_footer_html(
        build="MERYNA v1.0",
        coords=f"SKILLS {len(skill_names):02d} · TURNS {user_turns:03d} · "
        f"PROVIDER {prov_name.upper()}",
        extra="VOICE " + ("ON" if st.session_state.voice_enabled else "OFF"),
    ),
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar settings
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### ⚙️ Meryna Settings")
    st.session_state.voice_enabled = st.toggle(
        "Meryna speaks replies", value=st.session_state.voice_enabled
    )
    st.markdown("---")
    st.markdown("**Voice:** Uses your browser mic & speech synthesis")
    st.markdown(f"**Skills loaded:** {len(skill_names)}")
    for name in skill_names:
        st.markdown(f"- {name}")
    if st.button("🗑 Clear Chat"):
        st.session_state.messages = []
        st.session_state.greeted = False
        st.rerun()

# ---------------------------------------------------------------------------
# Resolve pending input
# ---------------------------------------------------------------------------

if "pending_input" in st.session_state:
    user_text = st.session_state.pop("pending_input")
elif send_clicked or (
    user_input and user_input != st.session_state.get("last_input", "")
):
    user_text = user_input
    st.session_state.last_input = user_input
else:
    user_text = None

# ---------------------------------------------------------------------------
# Process & respond via the shared platform
# ---------------------------------------------------------------------------

if user_text and user_text.strip():
    st.session_state.messages.append(
        {"role": "user", "content": user_text.strip()}
    )

    with st.spinner("Meryna is processing..."):
        try:
            response = _run(
                platform.process_utterance(user_text.strip(), session_id="web")
            )
            reply = response.text
        except Exception as exc:  # noqa: BLE001
            reply = (
                "Something went wrong while processing that. "
                "Please try again."
            )

    st.session_state.messages.append({"role": "assistant", "content": reply})

    # Browser speech synthesis (client-side) when voice is enabled.
    if st.session_state.voice_enabled and reply:
        js = BrowserTTSEngine().get_js(reply)
        st.components.v1.html(js, height=0)

    st.rerun()
