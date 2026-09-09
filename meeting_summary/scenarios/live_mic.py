"""Live captions on a periodic fragment; SDK threads only publish queue events."""

import hashlib

import streamlit as st

from . import register_scenario
from service_errors import safe_error_text
from speech_fast_transcription import AZURE_FAST, get_connection
from speech_streaming import LiveSpeechError, LiveSpeechSession
from translation import TARGET_LANGUAGES, TranslationError, get_translation_connection, translate_text


def _initialize_state():
    for key, value in {
        "live_session": None,
        "live_segments": [],
        "live_partial": "",
        "live_status": "idle",
        "live_errors": [],
        "live_notices": [],
        "live_translate_enabled": False,
        "live_target_lang": "zh-CN",
        "live_translation": None,
        "live_translation_error": None,
        "live_translate_pending": False,
        "live_true_text": False,
        "live_terminal": False,
    }.items():
        st.session_state.setdefault(key, value)


def _busy(session):
    return session is not None and (not session.closed or bool(session.cleanup_error))


def _drain_events(session):
    current = st.session_state.get("live_session")
    if current is None or current.session_id != session.session_id:
        return
    for event in session.drain():
        if event.session_id != current.session_id:
            continue
        if event.kind == "partial":
            st.session_state.live_partial = event.text
        elif event.kind == "final":
            st.session_state.live_segments.append(event.text)
            st.session_state.live_partial = ""
            if st.session_state.live_terminal:
                try:
                    print("[AVIA caption] " + event.text)
                except OSError as exc:
                    notice = "Could not write terminal captions: " + safe_error_text(exc)
                    if notice not in st.session_state.live_notices:
                        st.session_state.live_notices.append(notice)
        elif event.kind == "started":
            st.session_state.live_status = "stopping" if session.stopping else "listening"
        elif event.kind == "error":
            st.session_state.live_errors.append(event.text)
            st.session_state.live_translate_pending = False
        elif event.kind == "warning":
            st.session_state.live_notices.append(event.text)
        elif event.kind == "closed":
            st.session_state.live_partial = ""
            st.session_state.live_status = "error" if st.session_state.live_errors else "stopped"


def stop_live_capture() -> bool:
    """Return false rather than pretending that timed-out native cleanup succeeded."""
    _initialize_state()
    st.session_state.live_translate_pending = False
    session = st.session_state.live_session
    if session is None:
        return True
    st.session_state.live_status = "stopping"
    try:
        session.stop()
    except LiveSpeechError as exc:
        message = safe_error_text(exc)
        if message not in st.session_state.live_errors:
            st.session_state.live_errors.append(message)
        return False
    _drain_events(session)
    st.session_state.live_status = "error" if st.session_state.live_errors else "stopped"
    return True


def _clear_capture():
    st.session_state.update({
        "live_session": None,
        "live_segments": [],
        "live_partial": "",
        "live_status": "idle",
        "live_errors": [],
        "live_notices": [],
        "live_translation": None,
        "live_translation_error": None,
        "live_translate_pending": False,
    })


def _translate_saved():
    st.session_state.live_translate_pending = False
    text = " ".join(st.session_state.live_segments).strip()
    target = st.session_state.live_target_lang
    with st.spinner("Translating the stopped transcript with the configured Translator resource..."):
        try:
            translated = translate_text(text, target)
        except (ValueError, TranslationError) as exc:
            st.session_state.live_translation_error = str(exc)
        else:
            st.session_state.live_translation_error = None
            st.session_state.live_translation = {
                "text": translated,
                "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "target": target,
            }


@st.fragment(run_every=0.25)
def _live_panel():
    _initialize_state()
    session = st.session_state.live_session
    if session is not None:
        session.touch()
        _drain_events(session)
    busy = _busy(session)
    connection = None
    try:
        connection = get_connection(AZURE_FAST)
    except ValueError as exc:
        st.warning(str(exc))
    else:
        st.caption(f"Speech SDK: {connection.auth_mode} | {connection.endpoint}")
    with st.expander("Translation after Stop"):
        st.checkbox("Translate after Stop", key="live_translate_enabled", disabled=busy)
        st.selectbox("Target language", list(TARGET_LANGUAGES), key="live_target_lang", disabled=busy)
        st.caption("Uses only TRANSLATOR_* settings, never the Speech resource's region or credentials.")
        if st.session_state.live_translate_enabled:
            try:
                translator = get_translation_connection()
            except ValueError as exc:
                st.warning(str(exc))
            else:
                st.caption(f"Translator: {translator.auth_mode} | {translator.region} | {translator.endpoint}")
    with st.expander("Advanced"):
        st.checkbox("Enable TrueText post-processing (may slow captions)", key="live_true_text", disabled=busy)
        st.checkbox("Print final captions to the server terminal", key="live_terminal", disabled=busy)
        st.caption("Terminal output is opt-in and may be retained by your terminal. AVIA does not write transcript log files.")
    start_col, stop_col, clear_col = st.columns(3)
    start = start_col.button("Start", key="live_start", type="primary", disabled=busy or connection is None)
    stop = stop_col.button("Stop", key="live_stop", disabled=not busy or (session is not None and session.stopping))
    clear = clear_col.button("Clear", key="live_clear")
    if clear:
        st.session_state.live_translate_pending = False
        if stop_live_capture():
            _clear_capture()
    elif start and not busy and connection is not None:
        _clear_capture()
        session = LiveSpeechSession(connection=connection, true_text=st.session_state.live_true_text)
        st.session_state.live_session = session
        st.session_state.live_status = "starting"
        try:
            session.start()
        except LiveSpeechError as exc:
            st.session_state.live_errors.append(safe_error_text(exc))
            st.session_state.live_status = "error"
    elif stop and busy:
        if stop_live_capture():
            st.session_state.live_translate_pending = st.session_state.live_translate_enabled
    session = st.session_state.live_session
    if session is not None:
        _drain_events(session)
    busy = _busy(session)
    if busy:
        st.info("Stopping capture..." if session.stopping else (
            "Listening..." if st.session_state.live_status == "listening" else "Starting Speech connection..."
        ))
    for error in st.session_state.live_errors:
        st.error(error)
    for notice in st.session_state.live_notices:
        st.warning(notice)
    text = " ".join(st.session_state.live_segments).strip()
    st.subheader("Live transcription" if busy else "Saved transcription")
    with st.container(border=True):
        st.text(text or "No transcript yet.")
        if st.session_state.live_partial:
            st.caption("Interim caption (not final):")
            st.text(st.session_state.live_partial)
    if text:
        st.download_button(
            "Download transcript", text, file_name="live_transcript.txt", mime="text/plain",
            key="live_download", on_click="ignore",
        )
    if (
        not busy and st.session_state.live_translate_pending
        and text and not st.session_state.live_errors
    ):
        _translate_saved()
    if st.session_state.live_translate_enabled:
        if st.button("Translate saved transcript", disabled=busy or not text, key="live_translate") and not busy and text:
            _translate_saved()
    if st.session_state.live_translation_error:
        st.error("Translation failed: " + st.session_state.live_translation_error)
    saved = st.session_state.live_translation
    if saved is not None:
        if (
            saved["source_sha256"] != hashlib.sha256(text.encode("utf-8")).hexdigest()
            or saved["target"] != st.session_state.live_target_lang
        ):
            st.warning("The saved translation belongs to the earlier transcript or target language.")
        st.subheader("Saved translation (" + TARGET_LANGUAGES[saved["target"]] + ")")
        with st.container(border=True):
            st.text(saved["text"])
        st.download_button(
            "Download translation", saved["text"], file_name="live_translation.txt",
            mime="text/plain", key="live_download_translation", on_click="ignore",
        )


@register_scenario(
    key="live_mic",
    title="Live Microphone - Azure Speech SDK",
    description="English microphone captions with optional translation after Stop. This is not MAI file transcription.",
    keywords="Speech SDK | Key or Entra | Optional post-stop Translator",
)
def run():
    st.caption(
        "Captures the microphone on the computer running Streamlit, not the browser's microphone. "
        "Start begins a new transcript. Stop, Clear, and Back stop capture before proceeding. "
        "A disconnected/inactive workspace triggers shutdown after 30 seconds."
    )
    _live_panel()
