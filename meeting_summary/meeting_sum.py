import streamlit as st
from azure.cognitiveservices.speech import SpeechConfig, SpeechRecognizer, AudioConfig
import openai
import io
import speech_fast_transcription
import llm_analysis

# 设置页面配置
st.set_page_config(page_title="AVIA | Audio-Visual Intelligence Assistant", page_icon="🤖", layout="wide")

# 创建标题区域
st.markdown("""
<div style="text-align: center; padding: 2rem 0; background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); border-radius: 10px; margin-bottom: 2rem;">
    <h1 style="color: white; font-size: 3rem; margin: 0; text-shadow: 2px 2px 4px rgba(0,0,0,0.3);">🤖 AVIA</h1>
    <h2 style="color: white; font-size: 1.5rem; margin: 0.5rem 0 0 0; font-weight: 300;">Audio-Visual Intelligence Assistant</h2>
    <p style="color: rgba(255,255,255,0.9); font-size: 1.1rem; margin: 0.5rem 0 0 0;">Multi-language transcription • Image analysis • Intelligent summaries</p>
</div>
""", unsafe_allow_html=True)

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

        Bitte erstellen Sie eine umfassende Zusammenfassung mit Fokus auf wichtige Inhalte und Informationen.
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
