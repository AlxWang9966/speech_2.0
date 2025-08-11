from . import register_scenario
import streamlit as st
from llm_analysis import analysis_image  # fixed absolute import to avoid relative import error

@register_scenario(
    key="image_analysis",
    title="Image Understanding + Prompt",
    description="Upload an image and run GPT-4o vision with optional custom analysis prompt.",
    keywords="Azure OpenAI - Vision"
)
def run():
    st.subheader("Image Analysis")
    uploaded = st.file_uploader("Upload image", type=["png", "jpg", "jpeg", "gif", "webp"])
    user_prompt = st.text_area("Custom Analysis Prompt (optional)", placeholder="e.g., Identify UI usability issues and describe visual hierarchy.", height=100)
    col1, col2 = st.columns([1,1])
    if uploaded:
        with col1:
            st.image(uploaded, caption="Preview", use_column_width=True)
    if st.button("Analyze", type="primary", disabled=not uploaded):
        with st.spinner("Analyzing..."):
            result = analysis_image(uploaded, user_prompt=user_prompt)
        st.success("Analysis complete")
        st.markdown("### Result")
        st.write(result)
        st.download_button("Download Result", result, file_name="image_analysis.txt")
