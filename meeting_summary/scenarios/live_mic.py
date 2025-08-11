from . import register_scenario
import streamlit as st
import os, queue, time
import azure.cognitiveservices.speech as speechsdk
from azure.ai.translation.text import TextTranslationClient
from azure.core.credentials import AzureKeyCredential

@register_scenario(
    key="live_mic",
    title="Live Microphone Transcription + Translation",
    description="Continuously transcribe local microphone audio with optional real-time translation.",
    keywords="Azure Speech SDK - Continuous Recognition; Azure Translator"
)
def run():
    st.subheader("🎙️ Live Microphone Transcription")
    st.caption("Runs locally. Not browser streaming. Use for quick live caption + translation demos.")

    # State init
    for k, v in {
        'live_segments': [], 'live_partial': '', 'live_running': False,
        'live_recognizer': None, 'live_queue': queue.Queue(), 'live_last_refresh': 0.0,
        'live_translate_enabled': False, 'live_target_lang': 'zh-CN', 'live_translations': [],
        'live_translator_client': None
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Translation controls
    with st.expander("Translation Settings", expanded=False):
        st.session_state.live_translate_enabled = st.checkbox("Enable translation", value=st.session_state.live_translate_enabled)
        st.session_state.live_target_lang = st.selectbox(
            "Target language", ['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'],
            index=0 if st.session_state.live_target_lang not in ['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'] else ['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'].index(st.session_state.live_target_lang),
            disabled=not st.session_state.live_translate_enabled
        )

    col_a, col_b, col_c = st.columns([1,1,2])
    with col_a:
        start = st.button("▶️ Start", disabled=st.session_state.live_running)
    with col_b:
        stop = st.button("🛑 Stop", disabled=not st.session_state.live_running)
    with col_c:
        if st.button("🧹 Clear"):
            st.session_state.live_segments = []
            st.session_state.live_translations = []
            st.session_state.live_partial = ''

    if start and not st.session_state.live_running:
        speech_key = os.getenv('SPEECH_KEY')
        region = os.getenv('SPEECH_REGION','eastus')
        if not speech_key:
            st.error("SPEECH_KEY not set")
        else:
            try:
                config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
                config.set_property(speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption, "TrueText")
                audio_cfg = speechsdk.audio.AudioConfig(use_default_microphone=True)
                recognizer = speechsdk.SpeechRecognizer(speech_config=config, language="en-US", audio_config=audio_cfg)

                if st.session_state.live_translate_enabled:
                    t_key = os.getenv('TRANSLATOR_KEY')
                    t_region = os.getenv('TRANSLATOR_REGION') or region
                    t_endpoint = os.getenv('TRANSLATOR_ENDPOINT', 'https://api.cognitive.microsofttranslator.com')
                    if t_key:
                        try:
                            st.session_state.live_translator_client = TextTranslationClient(credential=AzureKeyCredential(t_key), region=t_region, endpoint=t_endpoint)
                        except Exception as te:
                            st.warning(f"Translator init failed: {te}")
                    else:
                        st.warning("Translator key missing; translation disabled")
                        st.session_state.live_translate_enabled = False

                qref = st.session_state.live_queue
                def _rec(evt: speechsdk.SpeechRecognitionEventArgs):
                    try:
                        if evt.result.reason == speechsdk.ResultReason.RecognizingSpeech:
                            qref.put(('partial', evt.result.text))
                    except Exception: pass
                def _final(evt: speechsdk.SpeechRecognitionEventArgs):
                    try:
                        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                            qref.put(('final', evt.result.text))
                    except Exception: pass
                def _stop(evt):
                    try: qref.put(('stopped', None))
                    except Exception: pass
                recognizer.recognizing.connect(_rec)
                recognizer.recognized.connect(_final)
                recognizer.session_stopped.connect(_stop)
                recognizer.canceled.connect(_stop)
                recognizer.start_continuous_recognition()
                st.session_state.live_recognizer = recognizer
                st.session_state.live_running = True
                st.success("Live session started")
            except Exception as e:
                st.error(f"Start failed: {e}")

    # Drain queue
    while st.session_state.live_queue and not st.session_state.live_queue.empty():
        kind, txt = st.session_state.live_queue.get()
        if kind == 'partial':
            st.session_state.live_partial = txt
        elif kind == 'final':
            st.session_state.live_segments.append(txt)
            st.session_state.live_partial = ''
            if st.session_state.live_translate_enabled and txt:
                client = st.session_state.live_translator_client
                if client:
                    try:
                        tr = client.translate(body=[txt], to_language=[st.session_state.live_target_lang])
                        translated = tr[0]['translations'][0]['text']
                    except Exception:
                        translated = '[Translation failed]'
                else:
                    translated = '[Translator not configured]'
                st.session_state.live_translations.append(translated)
        elif kind == 'stopped':
            st.session_state.live_running = False

    if stop and st.session_state.live_running and st.session_state.live_recognizer:
        try:
            st.session_state.live_recognizer.stop_continuous_recognition()
            st.session_state.live_running = False
            st.success("Stopped")
        except Exception as e:
            st.error(f"Stop failed: {e}")

    # Render
    if st.session_state.live_running:
        st.info("Speak now...")
    if st.session_state.live_partial:
        st.markdown(f"**Partial:** {st.session_state.live_partial}")
    if st.session_state.live_segments:
        st.markdown("**Final Segments:**")
        st.write("\n".join(st.session_state.live_segments))
        if st.session_state.live_translate_enabled and st.session_state.live_translations:
            st.markdown(f"**Translations ({st.session_state.live_target_lang}):**")
            st.write("\n".join(st.session_state.live_translations))
    if not st.session_state.live_running and not st.session_state.live_segments:
        st.caption("No transcript yet.")

    # Periodic refresh
    if st.session_state.live_running:
        now = time.time()
        if now - st.session_state.live_last_refresh > 1.0:
            st.session_state.live_last_refresh = now
            try: st.rerun()
            except AttributeError: st.experimental_rerun()
