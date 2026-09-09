"""Shared presentation only: no service calls, credentials, or capture state."""

from html import escape
from pathlib import Path

import streamlit as st

STYLE_FILE = Path(__file__).resolve().parent / "assets" / "studio.html"
WORKSPACES = {
    "audio_file_summary": {
        "title": "Audio transcription",
        "nav": "Audio lab",
        "icon": "audio",
        "material_icon": ":material/graphic_eq:",
        "tag": "MAI preview",
        "description": "Turn recordings into readable transcripts. Compare Azure Fast and MAI on the same audio.",
        "detail": "Matched comparisons / WER & CER / Export",
        "action": "Open audio lab",
        "eyebrow": "AUDIO WORKSPACE",
    },
    "live_mic": {
        "title": "Live captions",
        "nav": "Live captions",
        "icon": "mic",
        "material_icon": ":material/mic:",
        "tag": "Speech SDK",
        "description": "Stay with the conversation. Capture English captions, then translate after you stop.",
        "detail": "Continuous captions / Post-stop translation",
        "action": "Open live captions",
        "eyebrow": "LIVE WORKSPACE",
    },
    "image_analysis": {
        "title": "Image understanding",
        "nav": "Image studio",
        "icon": "image",
        "material_icon": ":material/image:",
        "tag": "GPT-4o",
        "description": "Give an image more context. Explore visual details with your own analysis prompt.",
        "detail": "Visual analysis / Custom prompts / Export",
        "action": "Open image studio",
        "eyebrow": "VISUAL WORKSPACE",
    },
}

ICON_GLYPHS = {
    "audio": "graphic_eq",
    "mic": "mic",
    "image": "image",
    "document": "description",
}


def icon(name: str) -> str:
    return f'<span class="avia-glyph" aria-hidden="true">{ICON_GLYPHS[name]}</span>'


def apply_theme(appearance: str) -> None:
    if appearance not in ("Light", "Dark"):
        raise ValueError("Appearance must be Light or Dark.")
    st.html(
        STYLE_FILE.read_text(encoding="utf-8")
        + f'<span data-avia-theme="{appearance.lower()}" aria-hidden="true"></span>'
    )


def brand() -> None:
    st.html(
        f'<div class="avia-brand"><span class="avia-logo">{icon("audio")}</span>'
        '<div><strong>AVIA</strong><small>AUDIO + VISUAL STUDIO</small></div></div>'
    )


def topbar(workspace: str = "Overview") -> None:
    st.html(
        '<div class="avia-topbar"><div>Workspace<span class="avia-divider">/</span>'
        f'<strong>{escape(workspace)}</strong></div>'
        '<span class="avia-tag avia-tag--neutral">Audio &amp; visual intelligence</span></div>'
    )


def hero() -> None:
    st.html(
        '<div class="avia-hero-copy"><p class="avia-kicker">LESS FRICTION. MORE CLARITY.</p>'
        '<h1>Your ideas.<br><span>A clearer picture.</span></h1>'
        '<p>One thoughtful workspace for spoken words and visual stories. '
        'Transcribe, compare, and find the details that matter.</p></div>'
    )


def workflow_illustration() -> None:
    heights = (10, 18, 14, 26, 38, 20, 46, 30, 52, 36, 64, 44, 28, 58, 40, 22,
               48, 34, 60, 42, 24, 54, 32, 20, 38, 26, 46, 18, 30, 14, 22, 10)
    bars = "".join(
        f'<span style="height:{height}px;opacity:{0.45 + (index % 5) * 0.1}"></span>'
        for index, height in enumerate(heights)
    )
    st.html(
        '<div class="avia-workflow" aria-hidden="true"><div class="avia-workflow-top">'
        '<p class="avia-kicker">FROM INPUT TO INSIGHT</p><span class="avia-tag">Your workflow</span></div>'
        f'<div class="avia-wave">{bars}</div>'
        '<div><div class="avia-workflow-line"></div><div class="avia-workflow-line"></div>'
        '<div class="avia-workflow-line"></div></div>'
        '<div class="avia-workflow-flow"><span>Capture</span><span>&rarr;</span>'
        '<span>Understand</span><span>&rarr;</span><strong>Make it useful</strong></div></div>'
    )


def section_heading(title: str, description: str) -> None:
    st.html(
        f'<div class="avia-section-heading"><h2>{escape(title)}</h2><p>{escape(description)}</p></div>'
    )


def workspace_card(presentation: dict) -> None:
    st.html(
        '<div class="avia-card"><div class="avia-card-top">'
        f'<span class="avia-icon">{icon(presentation["icon"])}</span>'
        f'<span class="avia-tag">{escape(presentation["tag"])}</span></div>'
        f'<h3>{escape(presentation["title"])}</h3><p>{escape(presentation["description"])}</p>'
        f'<div class="avia-card-detail">{escape(presentation["detail"])}</div></div>'
    )


def workspace_header(key: str, title: str, description: str) -> None:
    eyebrow = WORKSPACES.get(key, {}).get("eyebrow", "WORKSPACE")
    st.html(
        f'<div class="avia-workspace-header"><p class="avia-kicker">{escape(eyebrow)}</p>'
        f'<h1>{escape(title)}</h1><p>{escape(description)}</p></div>'
    )


def panel_heading(number: str, title: str, description: str = "") -> None:
    st.html(
        f'<div class="avia-panel-heading"><span class="avia-panel-number">{escape(number)}</span>'
        f'<div><h3>{escape(title)}</h3><p>{escape(description)}</p></div></div>'
    )


def empty_state(title: str, description: str, *, symbol: str = "document") -> None:
    st.html(
        f'<div class="avia-empty"><span class="avia-icon">{icon(symbol)}</span>'
        f'<h3>{escape(title)}</h3><p>{escape(description)}</p></div>'
    )


def metric_card(label: str, value: str, description: str) -> None:
    st.html(
        f'<div class="avia-metric"><div class="avia-metric-label">{escape(label)}</div>'
        f'<div class="avia-metric-value">{escape(value)}</div>'
        f'<div class="avia-metric-caption">{escape(description)}</div></div>'
    )


def capture_status(status: str, description: str) -> None:
    st.html(
        f'<div class="avia-status"><strong>{escape(status)}</strong><span>{escape(description)}</span></div>'
    )


def footer() -> None:
    st.html(
        '<div class="avia-footer"><span>Built for clarity, not guesswork.</span>'
        '<span>MAI is in preview. Your measurements tell your story.</span></div>'
    )
