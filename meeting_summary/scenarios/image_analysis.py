from . import register_scenario
import hashlib

import streamlit as st
import llm_analysis
import presentation as ui

@register_scenario(
    key="image_analysis",
    title="Image Understanding + Prompt",
    description="Upload an image and run GPT-4o vision with optional custom analysis prompt.",
    keywords="Azure OpenAI - Vision"
)
def run():
    with st.container(key="avia_image_columns"):
        source, output = st.columns([1, 1.15])
        with source, st.container(key="avia_panel_image_source"):
            ui.panel_heading("01", "A picture worth exploring", "Upload an image and tell AVIA what to look for.")
            uploaded = st.file_uploader(
                "Upload image", type=["png", "jpg", "jpeg", "gif", "webp"],
                key="image_upload", label_visibility="collapsed",
            )
            st.caption("PNG, JPEG, WebP, or non-animated GIF / Up to 20 MB")
            data = uploaded.getvalue() if uploaded is not None else None
            valid_image = False
            if data is not None:
                try:
                    llm_analysis.image_mime_type(data)
                except ValueError as exc:
                    st.warning(str(exc))
                else:
                    valid_image = True
                    st.image(data, caption="Your image", use_container_width=True)
            user_prompt = st.text_area(
                "Custom Analysis Prompt (optional)",
                placeholder="What should I notice? Try: Describe the visual hierarchy, or identify the key objects.",
                height=140,
                key="image_prompt",
            )
            signature = (hashlib.sha256(data).hexdigest(), uploaded.name, user_prompt.strip()) if data else None
            analyze = st.button(
                "Analyze", type="primary", disabled=not valid_image, key="image_analyze",
                use_container_width=True, icon=":material/auto_awesome:",
            )
            st.caption("Uses your configured Azure OpenAI resource. Analysis runs only when you choose.")
        with output, st.container(key="avia_panel_image_result"):
            ui.panel_heading("02", "See the bigger picture", "Your saved analysis stays here while you explore.")
            if analyze and valid_image:
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
                st.caption(saved["filename"] + " | Prompt: " + (saved["prompt"] or "Default image analysis"))
                st.write(saved["text"])
                st.divider()
                st.download_button(
                    "Download Result", saved["text"], file_name="image_analysis.txt",
                    mime="text/plain", key="image_download", on_click="ignore",
                    icon=":material/download:", use_container_width=True,
                )
            else:
                ui.empty_state(
                    "A fresh perspective awaits",
                    "Upload an image. Ask a focused question, or leave the prompt blank for a general analysis.",
                    symbol="image",
                )
