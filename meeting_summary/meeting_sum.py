import streamlit as st
from azure.cognitiveservices.speech import SpeechConfig, SpeechRecognizer, AudioConfig
import speech_fast_transcription
import llm_analysis
import realtime_stream  # Real-time (simulated file streaming) transcription
import os
import azure.cognitiveservices.speech as speechsdk  # Azure Speech SDK for live microphone
import queue, time  # Queue for thread-safe event passing; time for periodic rerun
from azure.ai.translation.text import TextTranslationClient  # Live translation client
from azure.core.credentials import AzureKeyCredential

"""
AVIA Main Streamlit App (meeting_sum.py)

Features:
- Batch audio transcription via Azure Fast Transcription API (multi-language autodetect)
- Image upload + multimodal analysis (Azure OpenAI Vision)
- Intelligent multilingual summary generation (Azure OpenAI)
- Simulated continuous transcription & translation (push-stream of uploaded file)
- Live local microphone continuous transcription (Azure Speech SDK) with optional on-the-fly translation

Design Notes:
- Background SDK callbacks MUST NOT touch Streamlit state directly (avoid ScriptRunContext warnings). They enqueue events.
- Main thread drains a Queue each rerun to update session_state (transcription + translations).
- Periodic rerun (st.rerun) every ~1s while live mic is running to keep UI responsive.
- Translation for live mic performed only on finalized segments (NOT partials) for accuracy & cost efficiency.
- Keep this script mostly orchestration; heavy logic lives in helper modules.

TODO (future enhancements): browser-based WebRTC capture, diarization in live mic mode, auto language detection for live mode, export/clear live transcript buttons.
"""

# ===== Page Configuration =====
st.set_page_config(page_title="AVIA | Audio-Visual Intelligence Assistant", page_icon="🤖", layout="wide")

# ===== Hero Banner =====
st.markdown("""
<div style="text-align: center; padding: 2rem 0; background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); border-radius: 10px; margin-bottom: 2rem;">
    <h1 style="color: white; font-size: 3rem; margin: 0; text-shadow: 2px 2px 4px rgba(0,0,0,0.3);">🤖 AVIA</h1>
    <h2 style="color: white; font-size: 1.5rem; margin: 0.5rem 0 0 0; font-weight: 300;">Audio-Visual Intelligence Assistant</h2>
    <p style="color: rgba(255,255,255,0.9); font-size: 1.1rem; margin: 0.5rem 0 0 0;">Multi-language transcription • Image analysis • Intelligent summaries</p>
</div>
""", unsafe_allow_html=True)

# ===== Main Content =====
# 创建两列布局
col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div style="background: #f8f9fa; padding: 1.5rem; border-radius: 10px; border-left: 4px solid #007bff;">
        <h3 style="color: #007bff; margin-top: 0;">🎤 Audio Processing</h3>
        <p style="color: #6c757d; margin-bottom: 1rem;">Upload audio files for multi-language transcription and intelligent analysis</p>
    </div>
    """, unsafe_allow_html=True)
    
    audio_file = st.file_uploader(
        "Choose Audio File", 
        type=["wav", "mp3", "m4a"],
        help="Supports: WAV, MP3, M4A formats. Automatic language detection for 7+ languages."
    )
    
    if audio_file:
        st.success("✅ Audio file uploaded successfully!")
        st.info(f"📁 File: {audio_file.name} ({audio_file.size} bytes)")
    
    # 新增实时转录选项
    real_time_mode = st.checkbox("Enable simulated continuous transcription + translation", help="Experimental: stream file to Azure Speech and translate segments.")

    # 实时转录 - 本地麦克风
    live_exp = st.expander("🎙️ Live Microphone (Local Machine)", expanded=False)
    with live_exp:
        st.caption("Runs only when this app is executed on your own machine with a microphone. Not browser-based streaming.")
        # ----- Session State Initialization (idempotent) -----
        if 'live_segments' not in st.session_state:
            st.session_state.live_segments = []          # Finalized transcript lines
        if 'live_partial' not in st.session_state:
            st.session_state.live_partial = ''           # Current partial hypothesis
        if 'live_running' not in st.session_state:
            st.session_state.live_running = False        # Live mic active flag
        if 'live_recognizer' not in st.session_state:
            st.session_state.live_recognizer = None      # SpeechRecognizer instance
        if 'live_queue' not in st.session_state:
            st.session_state.live_queue = queue.Queue()  # Thread-safe event queue
        if 'live_last_refresh' not in st.session_state:
            st.session_state.live_last_refresh = 0.0      # Timestamp for periodic rerun
        # Translation related state
        if 'live_translate_enabled' not in st.session_state:
            st.session_state.live_translate_enabled = False
        if 'live_target_lang' not in st.session_state:
            st.session_state.live_target_lang = 'zh-CN'
        if 'live_translations' not in st.session_state:
            st.session_state.live_translations = []      # Final translated lines aligned with segments
        if 'live_translator_client' not in st.session_state:
            st.session_state.live_translator_client = None

        # ----- Translation Controls (optional) -----
        st.markdown("---")
        col_cfg_a, col_cfg_b = st.columns([1,1])
        with col_cfg_a:
            st.session_state.live_translate_enabled = st.checkbox("Enable live translation", value=st.session_state.live_translate_enabled, help="Translate finalized segments to target language")
        with col_cfg_b:
            st.session_state.live_target_lang = st.selectbox(
                "Target",
                options=['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'],
                index=0 if st.session_state.live_target_lang not in ['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'] else ['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'].index(st.session_state.live_target_lang),
                disabled=not st.session_state.live_translate_enabled
            )

        # ----- Control Buttons -----
        col_live_a, col_live_b = st.columns(2)
        with col_live_a:
            start_live = st.button("▶️ Start Live Mic", disabled=st.session_state.live_running)
        with col_live_b:
            stop_live = st.button("🛑 Stop", disabled=not st.session_state.live_running)

        # ----- Start Live Recognition Logic -----
        if start_live and not st.session_state.live_running:
            speech_key = os.getenv('SPEECH_KEY')
            speech_region = os.getenv('SPEECH_REGION', 'eastus')
            if not speech_key:
                st.error("SPEECH_KEY not set in environment (.env).")
            else:
                try:
                    speech_config_live = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
                    speech_config_live.set_property(speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption, "TrueText")
                    audio_config_live = speechsdk.audio.AudioConfig(use_default_microphone=True)
                    # NOTE: Language hard-coded; future enhancement: auto-detect or user selector
                    recognizer_live = speechsdk.SpeechRecognizer(speech_config=speech_config_live, language="en-US", audio_config=audio_config_live)

                    # Initialize translator client if enabled (avoid doing this in callbacks)
                    if st.session_state.live_translate_enabled:
                        t_key = os.getenv('TRANSLATOR_KEY')
                        t_region = os.getenv('TRANSLATOR_REGION') or os.getenv('SPEECH_REGION', 'eastus')
                        t_endpoint = os.getenv('TRANSLATOR_ENDPOINT', 'https://api.cognitive.microsofttranslator.com')
                        if t_key:
                            try:
                                st.session_state.live_translator_client = TextTranslationClient(credential=AzureKeyCredential(t_key), region=t_region, endpoint=t_endpoint)
                            except Exception as te:
                                st.warning(f"Translator init failed: {te}")
                                st.session_state.live_translator_client = None
                        else:
                            st.warning("Translator key not set; translation disabled")
                            st.session_state.live_translate_enabled = False

                    # Capture queue reference (callbacks must not mutate st directly)
                    live_queue_ref = st.session_state.live_queue

                    def _live_recognizing(evt: speechsdk.SpeechRecognitionEventArgs):
                        """Interim hypothesis handler (enqueue partial)."""
                        try:
                            if evt.result.reason == speechsdk.ResultReason.RecognizingSpeech:
                                live_queue_ref.put(('partial', evt.result.text))
                        except Exception:
                            pass

                    def _live_recognized(evt: speechsdk.SpeechRecognitionEventArgs):
                        """Final segment handler (enqueue final)."""
                        try:
                            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                                live_queue_ref.put(('final', evt.result.text))
                        except Exception:
                            pass

                    def _live_canceled(evt: speechsdk.SessionEventArgs):  # noqa: D401
                        # Enqueue stop marker for graceful shutdown in main thread
                        try:
                            live_queue_ref.put(('stopped', None))
                        except Exception:
                            pass

                    def _live_stopped(evt):
                        # Session ended normally
                        try:
                            live_queue_ref.put(('stopped', None))
                        except Exception:
                            pass

                    # Wire events
                    recognizer_live.recognizing.connect(_live_recognizing)
                    recognizer_live.recognized.connect(_live_recognized)
                    recognizer_live.canceled.connect(_live_canceled)
                    recognizer_live.session_stopped.connect(_live_stopped)

                    recognizer_live.start_continuous_recognition()
                    st.session_state.live_recognizer = recognizer_live
                    st.session_state.live_running = True
                    st.success("Live microphone transcription started.")
                except Exception as e:
                    st.error(f"Failed to start live recognition: {e}")

        # ----- Drain Queue (Main Thread State Updates) -----
        while st.session_state.get('live_queue') and not st.session_state.live_queue.empty():
            kind, txt = st.session_state.live_queue.get()
            if kind == 'partial':
                st.session_state.live_partial = txt
            elif kind == 'final':
                st.session_state.live_segments.append(txt)
                st.session_state.live_partial = ''
                # Perform translation only for final segments
                if st.session_state.live_translate_enabled and txt:
                    client = st.session_state.live_translator_client
                    if client:
                        try:
                            tr = client.translate(body=[txt], to_language=[st.session_state.live_target_lang])
                            translated_text = tr[0]['translations'][0]['text']
                        except Exception:
                            translated_text = '[Translation failed]'
                    else:
                        translated_text = '[Translator not configured]'
                    st.session_state.live_translations.append(translated_text)
            elif kind == 'stopped':
                st.session_state.live_running = False

        # ----- Stop Logic -----
        if stop_live and st.session_state.live_running and st.session_state.live_recognizer:
            try:
                st.session_state.live_recognizer.stop_continuous_recognition()
                st.session_state.live_running = False
                st.success("Live microphone transcription stopped.")
            except Exception as e:
                st.error(f"Failed to stop recognizer: {e}")

        # ----- Live Output Rendering -----
        if st.session_state.live_running:
            st.info("Microphone active. Speak now...")
        if st.session_state.live_partial:
            st.markdown(f"**Partial:** {st.session_state.live_partial}")
        if st.session_state.live_segments:
            st.markdown("**Final Segments:**")
            st.write("\n".join(st.session_state.live_segments))
            if st.session_state.live_translate_enabled and st.session_state.live_translations:
                st.markdown(f"**Translations ({st.session_state.live_target_lang}):**")
                st.write("\n".join(st.session_state.live_translations))
        if not st.session_state.live_running and not st.session_state.live_segments:
            st.caption("No live transcription yet.")

        # ----- Periodic Auto-Refresh (while streaming) -----
        if st.session_state.live_running:
            now = time.time()
            if now - st.session_state.live_last_refresh > 1.0:
                st.session_state.live_last_refresh = now
                try:
                    st.rerun()
                except AttributeError:  # Older Streamlit fallback
                    st.experimental_rerun()

with col2:
    st.markdown("""
    <div style="background: #f8f9fa; padding: 1.5rem; border-radius: 10px; border-left: 4px solid #28a745;">
        <h3 style="color: #28a745; margin-top: 0;">🖼️ Visual Processing</h3>
        <p style="color: #6c757d; margin-bottom: 1rem;">Upload images for content analysis and OCR extraction</p>
    </div>
    """, unsafe_allow_html=True)
    
    image_file = st.file_uploader(
        "Choose Image File", 
        type=["jpg", "jpeg", "png"],
        help="Supports: JPG, JPEG, PNG formats. Analyzes content and extracts text information."
    )
    
    if image_file:
        st.success("✅ Image file uploaded successfully!")
        st.info(f"📁 File: {image_file.name} ({image_file.size} bytes)")

# 自定义提示区域
st.markdown("---")
st.markdown("""
<div style="background: #fff3cd; padding: 1rem; border-radius: 8px; border-left: 4px solid #ffc107; margin: 1rem 0;">
    <h4 style="color: #856404; margin-top: 0;">⚙️ Advanced Options</h4>
</div>
""", unsafe_allow_html=True)

user_prompt = st.text_area(
    "Custom Analysis Prompt (Optional)", 
    placeholder="Enter specific instructions for content analysis and summary generation...",
    help="Provide custom instructions to guide the AI analysis. Leave empty to use default intelligent analysis."
)

# 居中的处理按钮
st.markdown("<br>", unsafe_allow_html=True)
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    process_button = st.button(
        "🚀 Process with AVIA", 
        use_container_width=True,
        disabled=not (audio_file or image_file)
    )

if process_button and (audio_file or image_file):
    transcription = None
    image_result = None
    detected_language = "en-US"  # Default language
    
    # 处理进度指示器
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; margin: 2rem 0;">
        <h3 style="color: #495057;">🔄 AVIA Processing...</h3>
        <p style="color: #6c757d;">Analyzing your content with advanced AI capabilities</p>
    </div>
    """, unsafe_allow_html=True)
    
    with st.spinner("Processing with AVIA intelligence..."):
        # 转录音频
        if audio_file:
            st.info("🎤 Processing audio file...")
            result, detected_lang = speech_fast_transcription.fast_transcript(audio_file)
            
            if result:
                transcription = result
                detected_language = detected_lang if detected_lang else "en-US"
                st.success(f"✅ Audio transcription completed! Language detected: {detected_language}")
            else:
                transcription = "Audio transcription failed."
                st.error("❌ Audio transcription failed")

        # 分析图像内容
        if image_file:
            st.info("🖼️ Processing image file...")
            image_result = llm_analysis.analysis_image(image_file, detected_language)
            if image_result:
                st.success("✅ Image analysis completed!")
            else:
                st.error("❌ Image analysis failed")
        

        # 总结内容 - Create language-adaptive prompt
        st.info("🤖 Generating intelligent summary...")
        language_prompts = {
            "en-US": f"""
        Audio transcription: {transcription}
        Image analysis: {image_result}

        Please provide a comprehensive summary focusing on key content and important information.
        """,
            "zh-CN": f"""
        音频转录：{transcription}
        图像分析：{image_result}

        请提供一份侧重于关键内容和重要信息的总结。
        """,
            "es-ES": f"""
        Transcripción de audio: {transcription}
        Análisis de imagen: {image_result}

        Por favor, proporciona un resumen completo enfocándose en el contenido clave y la información importante.
        """,
            "fr-FR": f"""
        Transcription audio: {transcription}
        Analyse d'image: {image_result}

        Veuillez fournir un résumé complet en vous concentrant sur le contenu clé et les informations importantes.
        """,
            "de-DE": f"""
        Audio-Transkription: {transcription}
        Bildanalyse: {image_result}

        Bitte erstellen Sie eine umfassende Zusammenfassung mit Fokus auf wichtige Inhalte和信息。
        """,
            "ja-JP": f"""
        音声転写: {transcription}
        画像分析: {image_result}

        重要な内容と情報に焦点を当てた包括的な要約を提供してください。
        """,
            "ko-KR": f"""
        오디오 전사: {transcription}
        이미지 분석: {image_result}

        주요 내용과 중요한 정보에 중점을 둔 포괄적인 요약을 제공해 주세요.
        """
        }
        
        # Use detected language or default to English
        summary_prompt = language_prompts.get(detected_language, language_prompts["en-US"])

        summary = llm_analysis.analysis_text(user_prompt, summary_prompt, detected_language)
        st.success("✅ Summary generation completed!")
       


    # Language-adaptive UI labels
    ui_labels = {
        "en-US": {
            "transcription_header": "📝 Audio Transcription",
            "download_transcription": "Download Audio Transcription",
            "summary_header": "📝 Intelligent Summary"
        },
        "zh-CN": {
            "transcription_header": "📝 音频转录",
            "download_transcription": "下载音频转录",
            "summary_header": "📝 智能摘要"
        },
        "es-ES": {
            "transcription_header": "📝 Transcripción de Audio",
            "download_transcription": "Descargar Transcripción de Audio",
            "summary_header": "📝 Resumen Inteligente"
        },
        "fr-FR": {
            "transcription_header": "📝 Transcription Audio",
            "download_transcription": "Télécharger la Transcription Audio",
            "summary_header": "📝 Résumé Intelligent"
        },
        "de-DE": {
            "transcription_header": "📝 Audio-Transkription",
            "download_transcription": "Audio-Transkription Herunterladen",
            "summary_header": "📝 Intelligente Zusammenfassung"
        },
        "ja-JP": {
            "transcription_header": "📝 音声転写",
            "download_transcription": "音声転写をダウンロード",
            "summary_header": "📝 インテリジェント要約"
        },
        "ko-KR": {
            "transcription_header": "📝 오디오 전사",
            "download_transcription": "오디오 전사 다운로드",
            "summary_header": "📝 지능형 요약"
        }
    }
    
    labels = ui_labels.get(detected_language, ui_labels["en-US"])

    # 创建结果展示区域
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; margin: 2rem 0;">
        <h2 style="color: #495057;">📊 AVIA Analysis Results</h2>
        <p style="color: #6c757d;">Your content has been processed and analyzed</p>
    </div>
    """, unsafe_allow_html=True)

    # 结果布局
    if transcription and image_result:
        # 两列布局：转录和图像分析
        result_col1, result_col2 = st.columns(2)
        
        with result_col1:
            st.subheader(labels["transcription_header"])
            st.download_button(
                label=labels["download_transcription"],
                data=transcription,
                file_name="avia_transcription.txt",
                mime="text/plain",
                use_container_width=True
            )
        
        with result_col2:
            st.markdown("""
            <div style="background: #f0f8e7; padding: 1rem; border-radius: 8px; border-left: 4px solid #28a745;">
            """, unsafe_allow_html=True)
            st.subheader("🖼️ Image Analysis")
            if image_result:
                with st.expander("View Image Analysis Details", expanded=False):
                    st.write(image_result)
            st.markdown("</div>", unsafe_allow_html=True)
    
    elif transcription:
        # 只有音频
        st.subheader(labels["transcription_header"])
        st.download_button(
            label=labels["download_transcription"],
            data=transcription,
            file_name="avia_transcription.txt",
            mime="text/plain",
            use_container_width=True
        )
    
    elif image_result:
        # 只有图像
        st.markdown("""
        <div style="background: #f0f8e7; padding: 1.5rem; border-radius: 8px; border-left: 4px solid #28a745;">
        """, unsafe_allow_html=True)
        st.subheader("🖼️ Image Analysis")
        with st.expander("View Image Analysis Details", expanded=True):
            st.write(image_result)
        st.markdown("</div>", unsafe_allow_html=True)

    # 主要摘要区域
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("""
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 1.5rem; border-radius: 10px; margin: 1rem 0;">
        <h3 style="color: white; margin-top: 0; text-align: center;">✨ AVIA Intelligent Summary</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Summary content - just display the summary text
    st.write(summary)
    
    # Simple download button for the summary
    st.download_button(
        label="� Download Summary",
        data=summary,
        file_name="avia_summary.txt",
        mime="text/plain",
        use_container_width=True,
        help="Download summary as a text file"
    )

# 实时转录和翻译处理 - 新增逻辑
if audio_file and real_time_mode:
    st.info("🛰️ Starting simulated continuous transcription & translation...")
    with st.spinner("Streaming & processing..."):
        rt_result = realtime_stream.continuous_transcribe_and_translate(audio_file, source_language="en-US", target_language="zh-CN")
    if rt_result.error:
        st.error(f"Real-time module error: {rt_result.error}")
    else:
        st.success("✅ Continuous session completed")
        with st.expander("Real-time Segments", expanded=False):
            if rt_result.final_segments:
                st.markdown("**Original Segments:**")
                st.write("\n".join(rt_result.final_segments))
            if rt_result.translated_segments:
                st.markdown("**Translated Segments:**")
                st.write("\n".join(rt_result.translated_segments))
