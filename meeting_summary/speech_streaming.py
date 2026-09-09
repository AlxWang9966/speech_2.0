"""Continuous Speech SDK capture without any Streamlit calls or transcript files."""

from dataclasses import dataclass
import queue
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

import azure.cognitiveservices.speech as speechsdk
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential

from service_errors import safe_error_text
from speech_fast_transcription import AZURE_FAST, TOKEN_SCOPE, SpeechConnection, get_connection


class LiveSpeechError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeechEvent:
    session_id: str
    kind: str
    text: str = ""


def create_speech_config(
    connection: SpeechConnection, *, true_text: bool = False, credential=None,
) -> speechsdk.SpeechConfig:
    if connection.auth_mode == "entra":
        credential = credential or AzureCliCredential(process_timeout=30)
        try:
            credential.get_token(TOKEN_SCOPE)
        except ClientAuthenticationError as exc:
            raise LiveSpeechError(
                "Speech Entra sign-in failed. Install Azure CLI and run az login with the "
                "identity authorized for this Speech resource. No key fallback was made."
            ) from exc
        # The native SDK requests and renews tokens using the credential's expires_on.
        config = speechsdk.SpeechConfig(token_credential=credential, endpoint=connection.endpoint)
    elif connection.auth_mode == "key" and connection.key:
        host = urlsplit(connection.endpoint).hostname or ""
        if host.endswith(".cognitiveservices.azure.com"):
            config = speechsdk.SpeechConfig(subscription=connection.key, endpoint=connection.endpoint)
        elif host.endswith(".api.cognitive.microsoft.com"):
            config = speechsdk.SpeechConfig(subscription=connection.key, region=host.split(".")[0])
        else:
            raise ValueError("The live Speech endpoint must identify an Azure Speech resource.")
    else:
        raise ValueError("Live Speech requires the explicitly selected key or Entra configuration.")
    if true_text:
        config.set_property(speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption, "TrueText")
    return config


class LiveSpeechSession:
    """One capture owns its recognizer, worker, callbacks, and event queue."""

    def __init__(
        self, *, connection: SpeechConnection | None = None, audio_config=None,
        true_text: bool = False, inactivity_timeout: float | None = 30.0,
        startup_timeout: float = 45.0, credential=None,
    ):
        self.session_id = uuid4().hex
        self.connection = connection or get_connection(AZURE_FAST)
        self.events: queue.Queue[SpeechEvent] = queue.Queue()
        self.cleanup_error = ""
        self._audio_config = audio_config
        self._true_text = true_text
        self._inactivity_timeout = inactivity_timeout
        self._startup_timeout = startup_timeout
        self._credential = credential
        self._stop_requested = threading.Event()
        self._ended = threading.Event()
        self._listening = threading.Event()
        self._closed = threading.Event()
        self._event_lock = threading.Lock()
        self._accept_events = True
        self._heartbeat = time.monotonic()
        self._thread = None

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    @property
    def stopping(self) -> bool:
        return self._stop_requested.is_set() and not self.closed

    def touch(self) -> None:
        self._heartbeat = time.monotonic()

    def _emit(self, kind: str, text: str = "") -> None:
        with self._event_lock:
            if self._accept_events:
                self.events.put(SpeechEvent(self.session_id, kind, text))

    def drain(self) -> list[SpeechEvent]:
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                return events

    def start(self) -> None:
        if self._thread is not None or self.closed:
            raise LiveSpeechError("A capture cannot be restarted. Create a new session after stopping.")
        self.touch()
        self._thread = threading.Thread(target=self._run, name=f"avia-speech-{self.session_id}", daemon=True)
        try:
            self._thread.start()
        except RuntimeError as exc:
            self._closed.set()
            raise LiveSpeechError("Could not start the Speech capture worker.") from exc

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_requested.set()
        if self._thread is None:
            self._closed.set()
        if not self._closed.wait(timeout):
            raise LiveSpeechError(
                "Speech is still stopping; microphone release is not yet confirmed. "
                "Wait for shutdown before starting, clearing, or leaving this workspace."
            )
        if self.cleanup_error:
            raise LiveSpeechError(self.cleanup_error)

    def _on_partial(self, event) -> None:
        if event.result.reason == speechsdk.ResultReason.RecognizingSpeech:
            self._emit("partial", event.result.text)

    def _on_final(self, event) -> None:
        if event.result.reason == speechsdk.ResultReason.RecognizedSpeech and event.result.text:
            self._emit("final", event.result.text)

    def _on_started(self, _event) -> None:
        self._listening.set()
        self._emit("started")

    def _on_stopped(self, _event) -> None:
        self._ended.set()

    def _on_canceled(self, event) -> None:
        if event.reason == speechsdk.CancellationReason.Error:
            code = safe_error_text(event.error_code, self.connection.key, limit=100)
            detail = safe_error_text(event.error_details, self.connection.key)
            self._emit(
                "error",
                f"Speech recognition canceled ({code}). {detail} "
                "Check Speech authentication, data-plane access, endpoint, and network connectivity. "
                "No key fallback was made.",
            )
        elif event.reason != speechsdk.CancellationReason.EndOfStream:
            self._emit("warning", f"Speech recognition canceled: {safe_error_text(event.reason)}.")
        self._ended.set()

    def _inactive(self) -> bool:
        return (
            self._inactivity_timeout is not None
            and time.monotonic() - self._heartbeat > self._inactivity_timeout
        )

    def _run(self) -> None:
        recognizer = None
        config = None
        audio = None
        signals = []
        try:
            config = create_speech_config(
                self.connection, true_text=self._true_text, credential=self._credential,
            )
            if self._stop_requested.is_set() or self._inactive():
                return
            audio = self._audio_config
            if audio is None:
                audio = speechsdk.audio.AudioConfig(use_default_microphone=True)
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=config, language="en-US", audio_config=audio,
            )
            for signal, callback in (
                (recognizer.recognizing, self._on_partial),
                (recognizer.recognized, self._on_final),
                (recognizer.session_started, self._on_started),
                (recognizer.session_stopped, self._on_stopped),
                (recognizer.canceled, self._on_canceled),
            ):
                signal.connect(callback)
                signals.append(signal)
            recognizer.start_continuous_recognition_async().get()
            started_at = time.monotonic()
            while not self._stop_requested.wait(0.05) and not self._ended.is_set():
                if self._inactive():
                    self._emit(
                        "warning",
                        f"Capture stopped because the live workspace was inactive for {self._inactivity_timeout:g} seconds.",
                    )
                    break
                if not self._listening.is_set() and time.monotonic() - started_at > self._startup_timeout:
                    self._emit("error", "Speech connection startup timed out. Check authentication and endpoint connectivity.")
                    break
        except (RuntimeError, ValueError, OSError) as exc:
            self._emit("error", "Live Speech failed: " + safe_error_text(exc, self.connection.key))
        finally:
            self._stop_requested.set()
            if recognizer is not None:
                try:
                    recognizer.stop_continuous_recognition_async().get()
                except (RuntimeError, ValueError) as exc:
                    self.cleanup_error = (
                        "The Speech SDK could not confirm microphone shutdown. Restart this app process "
                        "before another capture. " + safe_error_text(exc, self.connection.key)
                    )
                    self._emit("error", self.cleanup_error)
                for signal in signals:
                    signal.disconnect_all()
            # Disconnect callbacks before dropping native SDK references. No public close() exists.
            signals.clear()
            recognizer = None
            audio = None
            self._audio_config = None
            if config is not None:
                close_credential = getattr(config.token_credential, "close", None)
                if callable(close_credential):
                    close_credential()
            config = None
            self._credential = None
            with self._event_lock:
                self._accept_events = False
                self.events.put(SpeechEvent(self.session_id, "closed"))
            self._closed.set()
