from . import register_scenario
import hashlib

import streamlit as st
import llm_analysis

@register_scenario(
    key="image_analysis",
    title="Image Understanding + Prompt",
    description="Upload an image and run GPT-4o vision with optional custom analysis prompt.",
    keywords="Azure OpenAI - Vision"
)
def run():
    st.subheader("Image Analysis")
    st.caption("Uses your existing Azure OpenAI endpoint/deployment. PNG, JPEG, WebP, or non-animated GIF; up to 20 MB.")
    uploaded = st.file_uploader("Upload image", type=["png", "jpg", "jpeg", "gif", "webp"], key="image_upload")
    user_prompt = st.text_area(
        "Custom Analysis Prompt (optional)",
        placeholder="e.g., Identify UI usability issues and describe visual hierarchy.",
        height=100,
        key="image_prompt",
    )
    data = uploaded.getvalue() if uploaded is not None else None
    signature = (hashlib.sha256(data).hexdigest(), uploaded.name, user_prompt.strip()) if data else None
    valid_image = False
    if data is not None:
        try:
            llm_analysis.image_mime_type(data)
        except ValueError as exc:
            st.warning(str(exc))
        else:
            valid_image = True
            with st.columns(2)[0]:
                st.image(data, caption="Preview", use_container_width=True)
    if st.button("Analyze", type="primary", disabled=not valid_image, key="image_analyze") and valid_image:
        with st.spinner("Analyzing..."):
            try:
                result = llm_analysis.analysis_image(uploaded, user_prompt=user_prompt)
            except (ValueError, llm_analysis.AnalysisError) as exc:
                st.session_state["image_analysis_error"] = {"signature": signature, "text": str(exc)}
            else:
                st.session_state["image_analysis_result"] = {
                    "signature": signature, "filename": uploaded.name,
                    "prompt": user_prompt.strip(), "text": result,
                }
                st.session_state.pop("image_analysis_error", None)
                st.success("Analysis complete")
    error = st.session_state.get("image_analysis_error")
    if error is not None and error["signature"] == signature:
        st.error("Image analysis failed: " + error["text"])
    saved = st.session_state.get("image_analysis_result")
    if saved is not None:
        if saved["signature"] != signature:
            st.warning("Inputs have changed. The saved analysis below belongs to the previous image and prompt.")
        st.subheader("Saved analysis")
        st.caption(saved["filename"] + " | Prompt: " + (saved["prompt"] or "Default image analysis"))
        st.write(saved["text"])
        st.download_button(
            "Download Result", saved["text"], file_name="image_analysis.txt",
            mime="text/plain", key="image_download", on_click="ignore",
        )
