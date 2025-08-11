from . import register_scenario
import streamlit as st
import speech_fast_transcription
import llm_analysis

@register_scenario(
    key="audio_file_summary",
    title="Upload Audio: Transcription + Summary",
    description="Upload an audio file for multi-language transcription and AI-generated summary.",
    keywords="Azure Speech - Fast Transcription; Azure OpenAI"
)
def run():
    st.subheader("🎧 Audio File Transcription & Summary")
    audio_file = st.file_uploader("Select audio", type=["wav","mp3","m4a"], help="Supported: wav/mp3/m4a")
    user_prompt = st.text_area("Custom Summary Prompt (optional)")

    if st.button("Process", disabled=not audio_file):
        with st.spinner("Transcribing..."):
            result, detected_lang = speech_fast_transcription.fast_transcript(audio_file)
        if not result:
            st.error("Transcription failed")
            return
        st.success(f"Transcription complete (language: {detected_lang})")
        with st.expander("View Raw Transcription", expanded=False):
            st.write(result)
        with st.spinner("Generating summary..."):
            summary = llm_analysis.analysis_text(user_prompt, f"Audio transcription: {result}", detected_lang)
        st.success("Summary ready")
        st.markdown("### Summary")
        st.write(summary)
        st.download_button("Download Transcription", result, file_name="transcription.txt")
        st.download_button("Download Summary", summary, file_name="summary.txt")
