from . import register_scenario
import streamlit as st
import llm_analysis

@register_scenario(
    key="image_analysis",
    title="Visual Content Recognition + Summary",
    description="Analyze uploaded images for visual content and generate descriptive insights.",
    keywords="Azure OpenAI Vision"
)
def run():
    image_file = st.file_uploader("Select image", type=["jpg","jpeg","png"])
    if image_file and st.button("Analyze"):
        with st.spinner("Analyzing image..."):
            analysis = llm_analysis.analysis_image(image_file)
        if analysis:
            st.success("Analysis complete")
            st.markdown("### Analysis Result")
            st.write(analysis)
            st.download_button("Download Result", analysis, file_name="image_analysis.txt")
        else:
            st.error("Analysis failed")
