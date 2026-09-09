import importlib
from pathlib import Path

from dotenv import load_dotenv
import streamlit as st

from scenarios import list_scenarios
from scenarios.live_mic import stop_live_capture

load_dotenv(Path(__file__).resolve().parent / ".env")
st.set_page_config(page_title="AVIA | Audio and Visual Intelligence", page_icon=":studio_microphone:", layout="wide")

_DEF_MODULES = [
    "scenarios.live_mic",
    "scenarios.audio_file_summary",
    "scenarios.image_analysis",
]
for module in _DEF_MODULES:
    importlib.import_module(module)
scenarios = list_scenarios()
st.session_state.setdefault("selected_scenario", None)

st.title("AVIA")
st.caption("Audio - Visual - Intelligence Assistant")

selected = st.session_state.selected_scenario
if selected in scenarios:
    if st.button("Back to scenarios"):
        if selected != "live_mic" or stop_live_capture():
            st.session_state.selected_scenario = None
            st.rerun()
        else:
            st.error("Capture shutdown is not yet confirmed. Stay here until Speech has stopped.")
    meta = scenarios[selected]
    st.header(meta["title"])
    st.write(meta["description"])
    st.caption(meta["keywords"])
    st.divider()
    meta["render"]()
else:
    st.header("Choose a workspace")
    st.write(
        "Use the transcription lab to evaluate MAI-Transcribe-2 on your audio. "
        "Live captions and image analysis remain separate workflows."
    )
    items = list(scenarios.items())
    for start in range(0, len(items), 3):
        row = items[start:start + 3]
        for (key, meta), column in zip(row, st.columns(len(row))):
            with column, st.container(border=True):
                st.subheader(meta["title"])
                st.write(meta["description"])
                st.caption(meta["keywords"])
                if st.button(
                    "Open workspace",
                    key=f"open_{key}",
                    type="primary" if key == "audio_file_summary" else "secondary",
                    use_container_width=True,
                ):
                    st.session_state.selected_scenario = key
                    st.rerun()
    st.info(
        "MAI-Transcribe-2 is in preview and is used for uploaded audio in AVIA, not live "
        "microphone streaming. Compare your own measured results; published model rankings "
        "are not guarantees for your recordings."
    )
