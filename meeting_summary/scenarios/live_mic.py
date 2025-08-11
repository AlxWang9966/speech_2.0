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
    # Init state defaults
    defaults = {
        'live_segments': [], 'live_partial': '', 'live_running': False,
        'live_recognizer': None, 'live_queue': queue.Queue(), 'live_last_refresh': 0.0,
        'live_translate_enabled': False, 'live_target_lang': 'zh-CN', 'live_translations': [],
        'live_translator_client': None
    }
    for k, v in defaults.items(): st.session_state.setdefault(k, v)

    # Translation controls
    with st.expander("Translation", expanded=False):
        st.session_state.live_translate_enabled = st.checkbox("Enable", value=st.session_state.live_translate_enabled)
        st.session_state.live_target_lang = st.selectbox(
            "Target", ['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'],
            index=['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'].index(st.session_state.live_target_lang),
            disabled=not st.session_state.live_translate_enabled
        )

    c1, c2, c3 = st.columns([1,1,2])
    start = c1.button("▶️ Start", disabled=st.session_state.live_running)
    stop  = c2.button("🛑 Stop", disabled=not st.session_state.live_running)
    if c3.button("🧹 Clear"):
        for k in ['live_segments','live_translations','live_partial']:
            st.session_state[k] = [] if 'segments' in k or 'translations' in k else ''

    if start and not st.session_state.live_running:
        key, region = os.getenv('SPEECH_KEY'), os.getenv('SPEECH_REGION','eastus')
        if not key: st.error("SPEECH_KEY missing")
        else:
            try:
                cfg = speechsdk.SpeechConfig(subscription=key, region=region)
                cfg.set_property(speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption, "TrueText")
                rec = speechsdk.SpeechRecognizer(speech_config=cfg, language="en-US", audio_config=speechsdk.audio.AudioConfig(use_default_microphone=True))
                if st.session_state.live_translate_enabled:
                    t_key = os.getenv('TRANSLATOR_KEY')
                    if t_key:
                        try:
                            st.session_state.live_translator_client = TextTranslationClient(credential=AzureKeyCredential(t_key), region=os.getenv('TRANSLATOR_REGION') or region, endpoint=os.getenv('TRANSLATOR_ENDPOINT','https://api.cognitive.microsofttranslator.com'))
                        except Exception as te: st.warning(f"Translator init failed: {te}")
                    else:
                        st.warning("Translator key missing")
                        st.session_state.live_translate_enabled = False
                q = st.session_state.live_queue
                rec.recognizing.connect(lambda e: q.put(('partial', e.result.text)) if e.result.reason == speechsdk.ResultReason.RecognizingSpeech else None)
                rec.recognized.connect(lambda e: q.put(('final', e.result.text)) if e.result.reason == speechsdk.ResultReason.RecognizedSpeech and e.result.text else None)
                rec.session_stopped.connect(lambda _: q.put(('stopped', None)))
                rec.canceled.connect(lambda _: q.put(('stopped', None)))
                rec.start_continuous_recognition()
                st.session_state.live_recognizer = rec
                st.session_state.live_running = True
                st.success("Started")
            except Exception as e:
                st.error(f"Start failed: {e}")

    # Queue drain
    q = st.session_state.live_queue
    while not q.empty():
        kind, txt = q.get()
        if kind == 'partial':
            st.session_state.live_partial = txt
        elif kind == 'final':
            st.session_state.live_segments.append(txt); st.session_state.live_partial = ''
            if st.session_state.live_translate_enabled and txt:
                client = st.session_state.live_translator_client
                if client:
                    try:
                        tr = client.translate(body=[txt], to_language=[st.session_state.live_target_lang])
                        st.session_state.live_translations.append(tr[0]['translations'][0]['text'])
                    except Exception: st.session_state.live_translations.append('[Translation failed]')
                else:
                    st.session_state.live_translations.append('[Translator not configured]')
        elif kind == 'stopped': st.session_state.live_running = False

    if stop and st.session_state.live_running and st.session_state.live_recognizer:
        try: st.session_state.live_recognizer.stop_continuous_recognition(); st.session_state.live_running = False; st.success("Stopped")
        except Exception as e: st.error(f"Stop failed: {e}")

    # Render transcript
    if st.session_state.live_running: st.info("Speak now...")
    if st.session_state.live_partial: st.markdown(f"**Partial:** {st.session_state.live_partial}")
    if st.session_state.live_segments:
        st.markdown("**Final Segments:**\n" + "\n".join(st.session_state.live_segments))
        if st.session_state.live_translate_enabled and st.session_state.live_translations:
            st.markdown(f"**Translations ({st.session_state.live_target_lang}):**\n" + "\n".join(st.session_state.live_translations))
    if not st.session_state.live_running and not st.session_state.live_segments: st.caption("No transcript yet.")

    # Periodic refresh
    if st.session_state.live_running and time.time() - st.session_state.live_last_refresh > 1:
        st.session_state.live_last_refresh = time.time()
        try: st.rerun()
        except Exception: pass
