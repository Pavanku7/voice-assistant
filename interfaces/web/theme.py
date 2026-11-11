"""
JARVIS / Ultron-style HUD theme for the Meryna web interface.

Renders a full sci-fi heads-up display: a glowing animated orb in the centre,
corner-bracketed side panels wired to real platform data, a top status bar and
a bottom telemetry footer.  Colour scheme: near-black canvas (``#040d18``) with
an electric-cyan accent (``#5ac8e8``) and Share Tech Mono / Rajdhani type.

Requirements addressed: 9.1
"""

from __future__ import annotations

from typing import Iterable

# JARVIS palette (exported for reuse / tests).
ACCENT_CYAN = "#5ac8e8"
BACKGROUND = "#040d18"
FONT_MONO = "Share Tech Mono"


def get_jarvis_css() -> str:
    """Return the full HUD dark-theme CSS block for the Streamlit interface."""
    return """
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@500;600;700&display=swap');

/* Hide Streamlit default chrome */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 0.6rem 1.4rem 2rem; max-width: 1200px; }
body, .stApp { background: #040d18 !important; }

/* Subtle starfield / vignette behind everything */
.stApp::before {
    content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background:
        radial-gradient(1px 1px at 20% 30%, rgba(90,200,232,0.35), transparent),
        radial-gradient(1px 1px at 70% 60%, rgba(90,200,232,0.30), transparent),
        radial-gradient(1px 1px at 40% 80%, rgba(90,200,232,0.25), transparent),
        radial-gradient(1px 1px at 85% 20%, rgba(90,200,232,0.30), transparent),
        radial-gradient(circle at 50% 45%, rgba(13,45,69,0.45), #040d18 70%);
}

/* ── Top status bar ───────────────────────────────────────────── */
.hud-topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 16px; margin-bottom: 12px;
    border: 1px solid #0e2d47; border-radius: 6px; background: #030a14cc;
    font-family: 'Share Tech Mono', monospace; letter-spacing: 2px;
}
.hud-topbar-id   { color: #2a8aaa; font-size: 11px; }
.hud-topbar-time { color: #5ac8e8; font-size: 13px; letter-spacing: 3px; }
.hud-topbar-status { color: #6be0a0; font-size: 11px; }
.hud-topbar-status .dot { animation: blink 1.6s ease-in-out infinite; }

/* ── Corner-bracketed panel ──────────────────────────────────── */
.hud-panel {
    position: relative; padding: 14px 14px 12px; margin-bottom: 14px;
    background: #050f1caa; border: 1px solid #0e2d4788; border-radius: 4px;
    /* four cyan corner brackets drawn with gradients */
    background-image:
      linear-gradient(#5ac8e8,#5ac8e8), linear-gradient(#5ac8e8,#5ac8e8),
      linear-gradient(#5ac8e8,#5ac8e8), linear-gradient(#5ac8e8,#5ac8e8),
      linear-gradient(#5ac8e8,#5ac8e8), linear-gradient(#5ac8e8,#5ac8e8),
      linear-gradient(#5ac8e8,#5ac8e8), linear-gradient(#5ac8e8,#5ac8e8);
    background-repeat: no-repeat;
    background-size: 14px 2px, 2px 14px, 14px 2px, 2px 14px,
                     14px 2px, 2px 14px, 14px 2px, 2px 14px;
    background-position:
      left top, left top, right top, right top,
      left bottom, left bottom, right bottom, right bottom;
}
.hud-panel-title {
    color: #5ac8e8; font-family: 'Rajdhani', sans-serif; font-weight: 700;
    font-size: 13px; letter-spacing: 3px; margin-bottom: 10px;
    border-bottom: 1px solid #0e2d47; padding-bottom: 6px;
    display: flex; justify-content: space-between; align-items: center;
}
.hud-panel-title .tag { color: #1e5a7a; font-size: 9px; font-family: 'Share Tech Mono',monospace; }
.hud-row {
    display: flex; justify-content: space-between; align-items: center;
    font-family: 'Share Tech Mono', monospace; font-size: 11px;
    padding: 3px 0; border-bottom: 1px dashed #0e2d4744;
}
.hud-label { color: #2a7a9a; letter-spacing: 1px; }
.hud-value { color: #8ecae6; letter-spacing: 1px; }
.hud-value.ok   { color: #6be0a0; }
.hud-value.warn { color: #e0b45a; }
.hud-value.off  { color: #7a4a4a; }
.hud-skill-list { max-height: 190px; overflow-y: auto; }
.hud-skill { color: #6fb8d6; font-family: 'Share Tech Mono',monospace; font-size: 10px;
             letter-spacing: 1px; padding: 2px 0; }
.hud-skill::before { content: "▸ "; color: #2a7a9a; }

/* ── Central orb stage ───────────────────────────────────────── */
.orb-stage {
    position: relative; display: flex; flex-direction: column;
    align-items: center; justify-content: center; height: 260px; margin: 4px 0 10px;
}
.orb {
    position: relative; width: 170px; height: 170px; border-radius: 50%;
    background: radial-gradient(circle at 50% 45%,
        rgba(120,220,255,0.55), rgba(30,90,130,0.25) 55%, transparent 72%);
    box-shadow: 0 0 55px rgba(90,200,232,0.45), inset 0 0 45px rgba(90,200,232,0.35);
    animation: orb-pulse 3.2s ease-in-out infinite;
}
.orb-ring {
    position: absolute; inset: -14px; border-radius: 50%;
    border: 1px solid rgba(90,200,232,0.55);
    border-left-color: transparent; border-right-color: transparent;
    animation: spin 7s linear infinite;
}
.orb-ring.two {
    inset: -26px; border: 1px dashed rgba(90,200,232,0.35);
    border-top-color: transparent; border-bottom-color: transparent;
    animation: spin 11s linear infinite reverse;
}
.orb-cross-v, .orb-cross-h {
    position: absolute; background: rgba(150,225,255,0.65);
    box-shadow: 0 0 8px rgba(90,200,232,0.8);
}
.orb-cross-v { top: -14px; bottom: -14px; left: 50%; width: 1px; transform: translateX(-50%); }
.orb-cross-h { left: -14px; right: -14px; top: 50%; height: 1px; transform: translateY(-50%); }
.orb-greeting {
    margin-top: 22px; color: #cfefff; font-family: 'Rajdhani', sans-serif;
    font-weight: 600; font-size: 30px; letter-spacing: 4px;
    text-shadow: 0 0 18px rgba(90,200,232,0.7);
}
.orb-subtitle {
    margin-top: 2px; color: #2a8aaa; font-family: 'Share Tech Mono', monospace;
    font-size: 10px; letter-spacing: 5px;
}
.orb.speaking { animation: orb-pulse 0.7s ease-in-out infinite; }

@keyframes orb-pulse {
    0%,100% { box-shadow: 0 0 45px rgba(90,200,232,0.35), inset 0 0 40px rgba(90,200,232,0.30); }
    50%     { box-shadow: 0 0 75px rgba(90,200,232,0.60), inset 0 0 55px rgba(90,200,232,0.45); }
}
@keyframes spin  { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.25; } }

/* ── Chat messages ───────────────────────────────────────────── */
.chat-wrap { margin: 6px 0 10px; }
.msg-meryna {
    background: #060f1c; border: 1px solid #0e2d47; border-radius: 10px 10px 10px 3px;
    padding: 9px 13px; margin: 6px 0; color: #8ecae6;
    font-family: 'Share Tech Mono',monospace; font-size: 13px; line-height: 1.6; max-width: 88%;
}
.msg-user {
    background: #0d2d45; border: 1px solid #175575; border-radius: 10px 10px 3px 10px;
    padding: 9px 13px; margin: 6px 0 6px auto; color: #a5d8f0;
    font-family: 'Share Tech Mono',monospace; font-size: 13px; line-height: 1.6;
    max-width: 88%; text-align: right;
}
.msg-label { font-size: 9px; color: #2a7a9a; letter-spacing: 2px; margin-bottom: 3px; }

/* ── Inputs & buttons ────────────────────────────────────────── */
.stTextInput > div > div > input {
    background: #070f1c !important; border: 1px solid #0e2d47 !important;
    color: #8ecae6 !important; font-family: 'Share Tech Mono',monospace !important;
    border-radius: 8px !important;
}
.stTextInput > div > div > input:focus { border-color: #1e5a7a !important; }
.stTextInput > div > div > input::placeholder { color: #1a4a5c !important; }
.stButton > button {
    background: #0d2d45 !important; border: 1px solid #175575 !important;
    color: #5ac8e8 !important; font-family: 'Share Tech Mono',monospace !important;
    letter-spacing: 1.5px; border-radius: 8px !important;
}
.stButton > button:hover { background: #1a3d57 !important; border-color: #2a7aaa !important; }

/* ── Bottom telemetry footer ─────────────────────────────────── */
.hud-footer {
    display: flex; justify-content: space-between; align-items: center;
    margin-top: 14px; padding: 6px 16px;
    border: 1px solid #0e2d47; border-radius: 6px; background: #030a14cc;
    font-family: 'Share Tech Mono', monospace; color: #2a7a9a;
    font-size: 10px; letter-spacing: 2px;
}
.hud-footer .accent { color: #5ac8e8; }
.divider { border: none; border-top: 1px solid #0e2d47; margin: 8px 0; }
</style>
"""


# ---------------------------------------------------------------------------
# HUD fragment builders
# ---------------------------------------------------------------------------


def get_top_bar_html(system_id: str, clock: str, online: bool = True) -> str:
    """Top status bar: system id (left), clock (centre), online state (right)."""
    status = (
        '<span class="dot">●</span> SYSTEM ONLINE'
        if online
        else '<span class="dot">●</span> DEGRADED'
    )
    return f"""
<div class="hud-topbar">
    <div class="hud-topbar-id">{system_id}</div>
    <div class="hud-topbar-time">{clock}</div>
    <div class="hud-topbar-status">{status}</div>
</div>
"""


def get_orb_html(greeting: str, subtitle: str, speaking: bool = False) -> str:
    """The central glowing orb with rotating rings, crosshair and greeting."""
    cls = "orb speaking" if speaking else "orb"
    return f"""
<div class="orb-stage">
    <div class="{cls}">
        <div class="orb-ring"></div>
        <div class="orb-ring two"></div>
        <div class="orb-cross-v"></div>
        <div class="orb-cross-h"></div>
    </div>
    <div class="orb-greeting">{greeting}</div>
    <div class="orb-subtitle">{subtitle}</div>
</div>
"""


def _row(label: str, value: str, value_cls: str = "") -> str:
    cls = f"hud-value {value_cls}".strip()
    return (
        f'<div class="hud-row"><span class="hud-label">{label}</span>'
        f'<span class="{cls}">{value}</span></div>'
    )


def get_left_panel_html(
    *,
    status_ok: bool,
    provider: str,
    model: str,
    fallback_ready: bool,
    skill_count: int,
    session_id: str,
    turns: int,
    voice_enabled: bool,
) -> str:
    """Left column: SYSTEM METRICS + NEURAL LINK panels (real platform data)."""
    metrics = "".join(
        [
            _row("STATUS", "ONLINE" if status_ok else "DEGRADED",
                 "ok" if status_ok else "warn"),
            _row("PROVIDER", provider.upper() or "N/A"),
            _row("MODEL", model or "N/A"),
            _row("FALLBACK", "READY" if fallback_ready else "OFFLINE",
                 "ok" if fallback_ready else "off"),
            _row("SKILLS", f"{skill_count:02d}"),
        ]
    )
    link = "".join(
        [
            _row("SESSION", session_id.upper()),
            _row("TURNS", f"{turns:03d}"),
            _row("VOICE", "ENABLED" if voice_enabled else "MUTED",
                 "ok" if voice_enabled else "off"),
            _row("LANG", "AUTO"),
        ]
    )
    return f"""
<div class="hud-panel">
    <div class="hud-panel-title">SYSTEM METRICS <span class="tag">CORE</span></div>
    {metrics}
</div>
<div class="hud-panel">
    <div class="hud-panel-title">NEURAL LINK <span class="tag">SESSION</span></div>
    {link}
</div>
"""


def get_right_panel_html(skill_names: Iterable[str]) -> str:
    """Right column: SKILL MATRIX listing every loaded skill (real data)."""
    names = list(skill_names)
    items = "".join(
        f'<div class="hud-skill">{n.replace("-skill", "").replace("-", " ").upper()}</div>'
        for n in names
    ) or '<div class="hud-skill">NO SKILLS LOADED</div>'
    return f"""
<div class="hud-panel">
    <div class="hud-panel-title">SKILL MATRIX <span class="tag">{len(names):02d} ACTIVE</span></div>
    <div class="hud-skill-list">{items}</div>
</div>
"""


def get_footer_html(build: str, coords: str, extra: str) -> str:
    """Bottom telemetry footer bar."""
    return f"""
<div class="hud-footer">
    <span>BUILD <span class="accent">{build}</span></span>
    <span>{coords}</span>
    <span><span class="accent">{extra}</span></span>
</div>
"""


# ---------------------------------------------------------------------------
# Backwards-compatible header (kept so older imports / tests keep working)
# ---------------------------------------------------------------------------


def get_header_html() -> str:
    """Legacy compact header bar (superseded by the full HUD)."""
    return get_top_bar_html("MERYNA-1", "SYSTEM ONLINE", online=True)
