"""Live microphone transcription + optional post-stop translation.

Key behaviors:
  * Azure Speech SDK continuous recognition for partial + final results.
  * Real-time terminal streaming (direct callback -> stdout) for minimal latency.
  * Streamlit UI updated via an event queue (avoids touching session state inside SDK threads).
  * One-shot full translation only after STOP (clearer, stable output).
  * Optional TrueText post-processing (may slow partial updates slightly).

Simplified: removed old mirror function & extraneous session keys; terminal streaming is always on.
"""

from . import register_scenario
import streamlit as st
import os, queue, time, sys, threading
import azure.cognitiveservices.speech as speechsdk
from azure.ai.translation.text import TextTranslationClient
from azure.core.credentials import AzureKeyCredential

LOG_FILE = os.path.join(os.getcwd(), 'live_mic_log.txt')

PARTIAL_RERUN_INTERVAL = 0.08   # minimum time between forced reruns on new partial
PASSIVE_REFRESH_INTERVAL = 0.12 # background refresh cadence while running


@register_scenario(
    key="live_mic",
    title="Live Microphone Transcription + Translation",
    description="Continuously transcribe local microphone audio with optional real-time translation.",
    keywords="Azure Speech SDK - Continuous Recognition; Azure Translator"
)
def run():
    # --- State initialization ---
    defaults = {
        'live_segments': [],
        'live_partial': '',
        'live_running': False,
        'live_recognizer': None,
        'live_queue': queue.Queue(),
        'live_last_refresh': 0.0,
        'live_translate_enabled': False,
        'live_target_lang': 'zh-CN',
        'live_translator_client': None,
        'live_full_translation': None,
        'live_true_text': False
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

    # --- Translation controls ---
    with st.expander("Translation", expanded=False):
        st.session_state.live_translate_enabled = st.checkbox("Enable", value=st.session_state.live_translate_enabled)
        st.session_state.live_target_lang = st.selectbox(
            "Target", ['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'],
            index=['zh-CN','en-US','ja-JP','ko-KR','fr-FR','de-DE','es-ES'].index(st.session_state.live_target_lang),
            disabled=not st.session_state.live_translate_enabled
        )

    with st.expander("Advanced", expanded=False):
        st.session_state.live_true_text = st.checkbox("Enable TrueText post-processing (may slow partial captions)", value=st.session_state.live_true_text)
        st.caption("Terminal streaming is always ON.")

    c1, c2, c3 = st.columns([1,1,2])
    start = c1.button("▶️ Start", disabled=st.session_state.live_running)
    stop  = c2.button("🛑 Stop", disabled=not st.session_state.live_running)
    if c3.button("🧹 Clear"):
        st.session_state.live_segments = []
        st.session_state.live_partial = ''
        st.session_state.live_full_translation = None

    if start and not st.session_state.live_running:
        key, region = os.getenv('SPEECH_KEY'), os.getenv('SPEECH_REGION','eastus')
        if not key: st.error("SPEECH_KEY missing")
        else:
            try:
                cfg = speechsdk.SpeechConfig(subscription=key, region=region)
                if st.session_state.live_true_text:
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
                # reset any previous full translation
                st.session_state.live_full_translation = None
                q = st.session_state.live_queue
                # Queue population for UI (avoid touching Streamlit in background threads except via queue)
                rec.recognizing.connect(
                    lambda e: q.put(('partial', e.result.text)) if e.result.reason == speechsdk.ResultReason.RecognizingSpeech else None
                )
                rec.recognized.connect(
                    lambda e: q.put(('final', e.result.text)) if e.result.reason == speechsdk.ResultReason.RecognizedSpeech and e.result.text else None
                )

                # Direct terminal streaming (low latency) – isolated from Streamlit session state
                term_lock = threading.Lock()
                term_cfg = {'last_inline_len': 0}

                def _cb_recognizing(evt: speechsdk.SessionEventArgs):
                    res = evt.result
                    if not res or res.reason != speechsdk.ResultReason.RecognizingSpeech:
                        return
                    line = res.text
                    if not line:
                        return
                    with term_lock:
                        prev = term_cfg['last_inline_len']
                        pad = ' ' * (prev - len(line)) if prev > len(line) else ''
                        try:
                            sys.stdout.write('\r' + line + pad)
                            sys.stdout.flush()
                        except Exception:
                            pass
                        term_cfg['last_inline_len'] = len(line)

                def _cb_recognized(evt: speechsdk.SessionEventArgs):
                    res = evt.result
                    if not res or res.reason != speechsdk.ResultReason.RecognizedSpeech or not res.text:
                        return
                    text = res.text
                    with term_lock:
                        if term_cfg['last_inline_len']:
                            try:
                                sys.stdout.write('\r' + ' ' * term_cfg['last_inline_len'] + '\r')
                                sys.stdout.flush()
                            except Exception:
                                pass
                            term_cfg['last_inline_len'] = 0
                        try:
                            print(text)
                        except Exception:
                            pass
                        try:
                            with open(LOG_FILE, 'a', encoding='utf-8') as lf:
                                lf.write(text + '\n')
                        except Exception:
                            pass

                rec.recognizing.connect(_cb_recognizing)
                rec.recognized.connect(_cb_recognized)
                rec.session_stopped.connect(lambda _: q.put(('stopped', None)))
                rec.canceled.connect(lambda _: q.put(('stopped', None)))
                rec.start_continuous_recognition()
                st.session_state.live_recognizer = rec
                st.session_state.live_running = True
                st.success("Started")
            except Exception as e:
                st.error(f"Start failed: {e}")

    # --- Drain event queue into session state (UI thread safe) ---
    q = st.session_state.live_queue
    partial_updated = False
    new_final = False
    while not q.empty():
        kind, txt = q.get()
        if kind == 'partial':
            st.session_state.live_partial = txt
            partial_updated = True
        elif kind == 'final':
            st.session_state.live_segments.append(txt); st.session_state.live_partial = ''
            new_final = True
        elif kind == 'stopped': st.session_state.live_running = False

    # Immediate rerun on fresh partial for snappier captioning
    if st.session_state.live_running and partial_updated:
        now = time.time()
        if now - st.session_state.live_last_refresh > PARTIAL_RERUN_INTERVAL:
            st.session_state.live_last_refresh = now
            try: st.rerun()
            except Exception: pass

    if stop and st.session_state.live_running and st.session_state.live_recognizer:
        try:
            st.session_state.live_recognizer.stop_continuous_recognition(); st.session_state.live_running = False; st.success("Stopped")
        except Exception as e: st.error(f"Stop failed: {e}")
        # Perform one-shot full translation after stopping (if enabled)
        if st.session_state.live_translate_enabled and st.session_state.live_segments:
            st.session_state.live_full_translation = None  # force recompute
    # (Terminal line cleared by callback logic.)

    # --- UI Rendering (seamless partial + final) ---
    if 'live_css_injected' not in st.session_state:
        st.markdown("""
        <style>
          .live-trans-box {background:#fff;border:1px solid #e1e5ec;border-radius:10px;padding:.75rem .9rem;min-height:140px;font-size:.85rem;line-height:1.15rem;white-space:pre-wrap;}
          .live-partial {color:#6a3fb4;font-style:italic;opacity:.85;}
          .live-empty {color:#8a94a3;}
        </style>
        """, unsafe_allow_html=True)
        st.session_state.live_css_injected = True

    if st.session_state.live_running:
        st.markdown("<div style='display:inline-flex;align-items:center;gap:.5rem;background:#ffeef5;border:1px solid #ffb9d0;color:#c5004f;font-size:.7rem;font-weight:600;padding:.4rem .7rem;border-radius:30px;margin:.4rem 0 .4rem'>🔴 Listening...</div>", unsafe_allow_html=True)
    final_text = " ".join(st.session_state.live_segments).strip()
    if st.session_state.live_running:
        if st.session_state.live_partial:
            html_text = f"{final_text + ' ' if final_text else ''}<span class='live-partial'>{st.session_state.live_partial}</span>"
        else:
            html_text = final_text if final_text else "<span class='live-empty'>Capturing…</span>"
    else:
        html_text = final_text if final_text else "<span class='live-empty'>No transcript yet.</span>"
    st.markdown("**Transcription (live)**" if st.session_state.live_running else "**Final Transcription**")
    st.markdown(f"<div class='live-trans-box'>{html_text}</div>", unsafe_allow_html=True)

    # Show translation only after stop (one-shot); attempt computation if missing
    if not st.session_state.live_running and st.session_state.live_translate_enabled and st.session_state.live_segments:
        if st.session_state.live_full_translation is None:
            full_text = " ".join(st.session_state.live_segments)
            client = st.session_state.live_translator_client
            if client:
                try:
                    tr = client.translate(body=[full_text], to_language=[st.session_state.live_target_lang])
                    st.session_state.live_full_translation = tr[0]['translations'][0]['text']
                except Exception as e:
                    st.session_state.live_full_translation = f"[Translation failed: {e}]"
            else:
                st.session_state.live_full_translation = '[Translator not configured]'
        trans_display = st.session_state.live_full_translation or '<span style="color:#8a94a3">Translating...</span>'
        st.markdown(f"**Translation ({st.session_state.live_target_lang})**")
        st.markdown(f"<div style='background:#f7f4ff;border:1px solid #d6cbf5;border-radius:10px;padding:.6rem .75rem;min-height:80px;font-size:.85rem;line-height:1.1rem;color:#1f2530;'>{trans_display}</div>", unsafe_allow_html=True)

    # Passive periodic refresh (helps advance UI if no new partial triggers rerun)
    if st.session_state.live_running and time.time() - st.session_state.live_last_refresh > PASSIVE_REFRESH_INTERVAL:
        st.session_state.live_last_refresh = time.time()
        try: st.rerun()
        except Exception: pass
