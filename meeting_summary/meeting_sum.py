import streamlit as st
from scenarios import list_scenarios
import importlib

st.set_page_config(page_title="AVIA | Modular AI Demos", page_icon="🤖", layout="wide")

# ===== Hero Banner =====
st.markdown("""
<div style='text-align:center;padding:1.8rem 0;background:linear-gradient(90deg,#667eea 0%,#764ba2 100%);border-radius:14px;margin-bottom:1.2rem;'>
  <h1 style='color:white;margin:0;font-size:2.9rem;letter-spacing:.5px;'>🤖 AVIA</h1>
  <p style='color:rgba(255,255,255,0.92);font-size:1.05rem;margin:.55rem 0 0;'>Audio · Vision · Intelligence Assistant</p>
</div>
""", unsafe_allow_html=True)

# ===== Feature + Design Notes Section =====
with st.container():
    colF, colD = st.columns([1,1])
    with colF:
        st.markdown("""
        <div style='background:#f8f9fc;border:1px solid #e3e6ec;border-radius:10px;padding:0.9rem 1rem;'>
        <h4 style='margin:0 0 .4rem;color:#374151;'>Key Capabilities</h4>
        <ul style='margin:0 0 .2rem 1.1rem;padding:0;font-size:.83rem;line-height:1.15rem;color:#4b5563;'>
          <li>Fast multi‑language audio transcription (auto detect)</li>
          <li>Audio file summarization (Azure OpenAI)</li>
          <li>Live mic continuous transcription + optional translation</li>
          <li>Visual content recognition & descriptive analysis</li>
          <li>Pluggable modular demo architecture</li>
        </ul>
        </div>
        """, unsafe_allow_html=True)
    with colD:
        st.markdown("""
        <div style='background:#f8f9fc;border:1px solid #e3e6ec;border-radius:10px;padding:0.9rem 1rem;'>
        <h4 style='margin:0 0 .4rem;color:#374151;'>Design Notes</h4>
        <ul style='margin:0 0 .2rem 1.1rem;padding:0;font-size:.83rem;line-height:1.15rem;color:#4b5563;'>
          <li>Thread‑safe queue decouples SDK callbacks from UI</li>
          <li>Periodic rerun refreshes live stream output</li>
          <li>Each demo is an isolated module (easy extension)</li>
          <li>Translation applied only to finalized segments</li>
          <li>Clean separation of UX vs service logic</li>
        </ul>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<h3 style='margin-top:1.0rem;'>Select a Scenario</h3>", unsafe_allow_html=True)
st.markdown("<p style='color:#6c757d;margin-top:-.2rem'>Choose a service demo module below. More coming soon.</p>", unsafe_allow_html=True)

# ===== Load & Register Scenario Modules =====
for module_name in ["scenarios.live_mic", "scenarios.audio_file_summary", "scenarios.image_analysis"]:
    importlib.import_module(module_name)
scenarios = list_scenarios()

if 'selected_scenario' not in st.session_state:
    st.session_state.selected_scenario = None

# ===== Scenario Detail View =====
if st.session_state.selected_scenario and st.session_state.selected_scenario in scenarios:
    meta = scenarios[st.session_state.selected_scenario]
    top_cols = st.columns([1,7])
    with top_cols[0]:
        if st.button("← Back", key="back_btn"):
            st.session_state.selected_scenario = None
            try: st.rerun()
            except AttributeError: pass
    with top_cols[1]:
        st.markdown(f"<div style='margin-top:.2rem'><span style='font-size:1.9rem;font-weight:600;color:#343a40'>{meta['title']}</span></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:.75rem;color:#8854d0;background:#efeafd;display:inline-block;padding:.25rem .55rem;border-radius:4px;margin-top:.5rem'>{meta['keywords']}</div>", unsafe_allow_html=True)
        st.markdown(f"<p style='font-size:.85rem;color:#4b5563;margin-top:.7rem'>{meta['description']}</p>", unsafe_allow_html=True)
    st.markdown("<hr style='margin:1rem 0 1.2rem;border:none;border-top:1px solid #e4e6eb' />", unsafe_allow_html=True)
    scenarios[st.session_state.selected_scenario]['render']()
else:
    # ===== Card Styles =====
    st.markdown("""
    <style>
      .avia-grid {margin-top:.4rem;}
      .avia-card {background:linear-gradient(135deg,#ffffff 0%,#f5f7fa 100%);border:1px solid #e3e6ec;border-radius:16px;padding:1.1rem 1.05rem 1rem;position:relative;min-height:210px;display:flex;flex-direction:column;box-shadow:0 2px 6px rgba(20,30,60,.04);transition:box-shadow .18s, transform .18s;}
      .avia-card:hover {box-shadow:0 6px 22px -4px rgba(20,30,60,.15);transform:translateY(-3px);}
      .avia-title {font-size:1.15rem;font-weight:600;line-height:1.25rem;color:#262b33;margin:0 0 .55rem;}
      .avia-desc {font-size:.78rem;line-height:1.05rem;color:#4b5563;margin:0 0 .75rem;flex:1 0 auto;}
      .avia-key {font-size:.6rem;letter-spacing:.3px;color:#6941c6;background:#efeafd;padding:.32rem .55rem;border-radius:4px;display:inline-block;}
      .avia-open-btn {width:100%;border:none;border-radius:10px;background:linear-gradient(90deg,#667eea,#764ba2);color:#fff;font-weight:600;padding:.55rem 0;font-size:.8rem;cursor:pointer;}
      .avia-open-btn:hover {filter:brightness(1.05);} 
      .avia-open-wrapper {margin-top:.3rem;}
    </style>
    """, unsafe_allow_html=True)

    cards_per_row = 3
    items = list(scenarios.items())
    for i in range(0, len(items), cards_per_row):
        row = items[i:i+cards_per_row]
        cols = st.columns(len(row))
        for (key, meta), col in zip(row, cols):
            with col:
                # Build card
                short_desc = (meta['description'][:120] + '…') if len(meta['description']) > 120 else meta['description']
                st.markdown(f"""
                <div class='avia-card'>
                  <div class='avia-title'>{meta['title']}</div>
                  <div class='avia-desc'>{short_desc}</div>
                  <div class='avia-key'>{meta['keywords']}</div>
                  <div class='avia-open-wrapper'>
                    <form action='' method='post'>
                      <button class='avia-open-btn' type='submit'>Open</button>
                    </form>
                </div>
                </div>
                """, unsafe_allow_html=True)
                # Real button for state change (below card for reliability)
                if st.button(f"Open ▶ {meta['title']}", key=f"open_{key}", use_container_width=True):
                    st.session_state.selected_scenario = key
                    try: st.rerun()
                    except AttributeError: pass
    st.markdown("<hr style='margin:1.4rem 0 .8rem;border:none;border-top:1px solid #e4e6eb' />", unsafe_allow_html=True)
    st.caption("To add a new demo: create a module under meeting_summary/scenarios and register it in __init__. Registered modules auto‑render here.")
