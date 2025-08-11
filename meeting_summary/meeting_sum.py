import streamlit as st
from scenarios import list_scenarios
import importlib

# Optional external card component
try:
    from streamlit_card import card as st_card  # type: ignore
except Exception:
    st_card = None

st.set_page_config(page_title="AVIA | Modular AI Demos", page_icon="🤖", layout="wide")

# ===== Helpers =====
_DEF_MODULES = ["scenarios.live_mic", "scenarios.audio_file_summary", "scenarios.image_analysis"]
for m in _DEF_MODULES: importlib.import_module(m)
scenarios = list_scenarios()
if 'selected_scenario' not in st.session_state: st.session_state.selected_scenario = None

def _safe_rerun():
    try: st.rerun()
    except Exception: pass

# ===== Hero Banner =====
st.markdown("""
<style>
  body {background:linear-gradient(180deg,#f6f8fc 0%,#eef2f9 42%,#e9eef8 100%) !important;}
  .block-container {padding-top:1rem; max-width:1400px; margin:auto;}
  .avia-hero {text-align:center;padding:1.9rem 0 2.0rem;background:linear-gradient(90deg,#667eea 0%,#715edc 50%,#764ba2 100%);border-radius:32px;margin-bottom:1.3rem;}
  .avia-hero h1 {margin:0;font-size:3.0rem;letter-spacing:.55px;font-weight:800;display:flex;align-items:center;justify-content:center;gap:.6rem;}
  .avia-logo-text {background:linear-gradient(95deg,#ffffff 0%,#f1f5ff 32%,#f8f1ff 68%,#ffffff 100%);-webkit-background-clip:text;color:transparent;text-shadow:0 0 8px rgba(255,255,255,.35);} 
  .avia-hero p {color:rgba(255,255,255,0.95);font-size:1.06rem;margin:.65rem 0 0;letter-spacing:.4px;}
  /* Card styles (single definition) */
  .avia-card {background:linear-gradient(#ffffff,#ffffff) padding-box,linear-gradient(135deg,#667eea,#764ba2) border-box;border:1px solid transparent;border-radius:18px;padding:1.05rem 1rem 1rem;min-height:205px;display:flex;flex-direction:column;box-shadow:0 4px 14px -6px rgba(40,60,120,.16);transition:box-shadow .18s, transform .18s;}
  .avia-card:hover {box-shadow:0 10px 26px -6px rgba(40,60,120,.28);transform:translateY(-4px);}      
  .avia-title {font-size:1.1rem;font-weight:600;line-height:1.25rem;color:#1f2530;margin:0 0 .55rem;letter-spacing:.25px;}
  .avia-desc {font-size:.75rem;line-height:1.05rem;color:#414c5c;margin:0 0 .65rem;flex:1 0 auto;}
  .avia-key {font-size:.55rem;letter-spacing:.35px;color:#5a36b9;background:#efeafd;padding:.36rem .6rem;border-radius:30px;display:inline-block;}
</style>
<div class='avia-hero'>
  <h1><span>🤖</span><span class='avia-logo-text'>AVIA</span></h1>
  <p>Audio · Visual · Intelligence Assistant</p>
</div>
""", unsafe_allow_html=True)

# ===== Feature / Design Notes (kept concise) =====
if not st.session_state.selected_scenario:
    # Enhanced bullet styling
    st.markdown("""
    <style>
      .avia-bullets {list-style:none;margin:.1rem 0 0;padding:0;}
      .avia-bullets li {position:relative;margin:0 0 .55rem;padding:.55rem .75rem .55rem 2.3rem;background:#ffffffcc;border:1px solid #e2e6f0;border-radius:12px;font-size:.93rem;line-height:1.15rem;color:#1f2530;font-weight:500;backdrop-filter:blur(2px);} 
      .avia-bullets li:last-child {margin-bottom:0;}
      .avia-bullets li:before {content:"✔";position:absolute;left:.9rem;top:.58rem;font-size:.85rem;color:#5a36b9;font-weight:700;text-shadow:0 0 4px rgba(118,75,162,.25);} 
      @media (prefers-color-scheme: dark) { .avia-bullets li {background:#ffffff1a;color:#f5f7fa;border-color:#5f6572;} }
    </style>
    """, unsafe_allow_html=True)
    colF, colD = st.columns(2)
    with colF:
        st.markdown("""
        <ul class='avia-bullets'>
          <li>Fast multi‑language transcription</li>
          <li>Live mic + optional translation</li>
          <li>Audio & image AI analysis</li>
        </ul>
        """, unsafe_allow_html=True)
    with colD:
        st.markdown("""
        <ul class='avia-bullets'>
          <li>Queued streaming callbacks</li>
          <li>Modular scenario registry</li>
          <li>Separation of UI / services</li>
        </ul>
        """, unsafe_allow_html=True)

# ===== Scenario Detail =====
if st.session_state.selected_scenario in scenarios:
    meta = scenarios[st.session_state.selected_scenario]
    back_col, body_col = st.columns([1,7])
    with back_col:
        if st.button("← Back"):
            st.session_state.selected_scenario = None
            _safe_rerun()
    with body_col:
        st.markdown(f"<div style='margin-top:.15rem'><span style='font-size:1.85rem;font-weight:640;color:#ffffff;text-shadow:0 2px 6px rgba(20,30,60,.35)'>{meta['title']}</span></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:.68rem;color:#ffffff;background:rgba(255,255,255,0.18);backdrop-filter:blur(4px);display:inline-block;padding:.30rem .6rem;border-radius:6px;margin-top:.55rem;border:1px solid rgba(255,255,255,0.35)'>{meta['keywords']}</div>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-size:.8rem;color:#f2f4f8;margin-top:.55rem;text-shadow:0 1px 3px rgba(20,30,60,.35)'>{meta['description']}</p>", unsafe_allow_html=True)
    st.markdown("<hr style='margin:.9rem 0 1.1rem;border:none;border-top:1px solid rgba(255,255,255,0.35)' />", unsafe_allow_html=True)
    scenarios[st.session_state.selected_scenario]['render']()
else:
    st.markdown("<h3 style='margin-top:.6rem;'>Select a Scenario</h3>", unsafe_allow_html=True)
    # Render cards
    items = list(scenarios.items())
    per_row = 3
    for i in range(0, len(items), per_row):
        cols = st.columns(min(per_row, len(items) - i))
        for (key, meta), col in zip(items[i:i+per_row], cols):
            with col:
                desc = meta['description']
                short = desc if len(desc) <= 118 else desc[:115] + '…'
                if st_card:  # Component path
                    clicked = st_card(
                        title=meta['title'],
                        text=[short, meta['keywords']],
                        image=None,
                        styles={
                            "card": {"width": "100%", "height": "205px", "border-radius": "18px", "background": "linear-gradient(#ffffff,#ffffff) padding-box, linear-gradient(135deg,#667eea,#764ba2) border-box", "border": "1px solid transparent", "padding": "16px 16px 14px", "box-shadow": "0 4px 14px -6px rgba(40,60,120,.16)", "transition": "box-shadow .18s, transform .18s", "cursor": "pointer", "display": "flex", "flex-direction": "column"},
                            "title": {"font-size": "1.02rem", "font-weight": "600", "margin": "0 0 8px", "color": "#1f2530"},
                            "text": {"font-size": ".7rem", "line-height": "1.0rem", "color": "#414c5c"},
                            "div": {"font-size": ".5rem", "margin-top": "6px", "color": "#5a36b9", "background": "#efeafd", "display": "inline-block", "padding": "4px 9px", "border-radius": "20px"},
                            "filter": {"background-color": "rgba(255,255,255,0)"}
                        },
                        key=f"card_{key}"
                    )
                    if clicked:
                        st.session_state.selected_scenario = key
                        _safe_rerun()
                else:  # Minimal fallback
                    if st.button(meta['title']):
                        st.session_state.selected_scenario = key
                        _safe_rerun()
    st.markdown("<hr style='margin:1.2rem 0 .7rem;border:none;border-top:1px solid #dfe3eb' />", unsafe_allow_html=True)
    st.caption("Add a new demo: create a module under meeting_summary/scenarios and register it. It appears automatically.")
