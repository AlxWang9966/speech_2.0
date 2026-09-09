import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import azure.cognitiveservices.speech as speechsdk
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError

from speech_fast_transcription import SpeechConnection
from speech_streaming import LiveSpeechError, LiveSpeechSession, create_speech_config
from tests.helpers import TEST_CONNECTION


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect_all(self):
        self.callbacks.clear()

    def emit(self, event=None):
        for callback in list(self.callbacks):
            callback(event)


class Future:
    def __init__(self, action):
        self.action = action

    def get(self):
        return self.action()


def recognition_event(text, *, partial=False):
    return SimpleNamespace(result=SimpleNamespace(
        text=text,
        reason=speechsdk.ResultReason.RecognizingSpeech if partial else speechsdk.ResultReason.RecognizedSpeech,
    ))


class FakeRecognizer:
    def __init__(self):
        for name in ("recognizing", "recognized", "session_started", "session_stopped", "canceled"):
            setattr(self, name, Signal())
        self.started = threading.Event()
        self.stop_gate = None
        self.stop_calls = 0
        self.final_on_stop = ""
        self.start_event_enabled = True
        self.stop_error = None

    def start_continuous_recognition_async(self):
        def start():
            if self.start_event_enabled:
                self.session_started.emit()
            self.started.set()
        return Future(start)

    def stop_continuous_recognition_async(self):
        def stop():
            self.stop_calls += 1
            if self.stop_gate is not None:
                self.stop_gate.wait(5)
            if self.stop_error is not None:
                raise self.stop_error
            if self.final_on_stop:
                self.recognized.emit(recognition_event(self.final_on_stop))
            self.session_stopped.emit()
        return Future(stop)


class SpeechConfigurationTests(unittest.TestCase):
    @patch("speech_streaming.speechsdk.SpeechConfig")
    def test_custom_key_endpoint_and_true_text_are_preserved(self, config):
        create_speech_config(TEST_CONNECTION, true_text=True)
        config.assert_called_once_with(subscription=TEST_CONNECTION.key, endpoint=TEST_CONNECTION.endpoint)
        config.return_value.set_property.assert_called_once_with(
            speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption, "TrueText",
        )

    @patch("speech_streaming.speechsdk.SpeechConfig")
    def test_regional_sdk_configuration_uses_the_selected_endpoint_region(self, config):
        connection = SpeechConnection("https://eastasia.api.cognitive.microsoft.com", key="test", region="eastus")
        create_speech_config(connection)
        config.assert_called_once_with(subscription="test", region="eastasia")

    @patch("speech_streaming.speechsdk.SpeechConfig")
    @patch("speech_streaming.AzureCliCredential")
    def test_entra_passes_renewable_credential_to_native_sdk_not_a_static_token(self, credential, config):
        credential.return_value.get_token.return_value = AccessToken("unit-test-token", int(time.time()) + 3600)
        connection = SpeechConnection(TEST_CONNECTION.endpoint, auth_mode="entra")
        create_speech_config(connection)
        config.assert_called_once_with(token_credential=credential.return_value, endpoint=TEST_CONNECTION.endpoint)
        credential.return_value.get_token.assert_called_once()
        self.assertNotIn("auth_token", config.call_args.kwargs)
        self.assertNotIn("subscription", config.call_args.kwargs)

    @patch("speech_streaming.speechsdk.SpeechConfig")
    @patch("speech_streaming.AzureCliCredential")
    def test_credential_failure_prevents_sdk_start_and_key_fallback(self, credential, config):
        credential.return_value.get_token.side_effect = ClientAuthenticationError("private diagnostic")
        with self.assertRaisesRegex(LiveSpeechError, "No key fallback"):
            create_speech_config(SpeechConnection(TEST_CONNECTION.endpoint, auth_mode="entra"))
        config.assert_not_called()


class StreamingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.recognizer = FakeRecognizer()
        self.configuration = patch(
            "speech_streaming.create_speech_config", return_value=SimpleNamespace(token_credential=None),
        ).start()
        self.factory = patch("speech_streaming.speechsdk.SpeechRecognizer", return_value=self.recognizer).start()
        self.microphone = patch("speech_streaming.speechsdk.audio.AudioConfig").start()
        self.addCleanup(patch.stopall)

    def start_capture(self, **kwargs):
        session = LiveSpeechSession(connection=TEST_CONNECTION, audio_config=object(), **kwargs)
        self.addCleanup(lambda: session.stop(timeout=2) if not session.closed else None)
        session.start()
        self.assertTrue(self.recognizer.started.wait(2))
        return session

    def test_stop_keeps_tail_results_and_disconnects_every_callback(self):
        self.recognizer.final_on_stop = "Last sentence during stop."
        session = self.start_capture()
        self.recognizer.recognizing.emit(recognition_event("Interim", partial=True))
        self.recognizer.recognized.emit(recognition_event("First sentence."))
        session.stop()
        events = session.drain()
        self.assertEqual([event.text for event in events if event.kind == "final"],
                         ["First sentence.", "Last sentence during stop."])
        self.assertEqual(events[-1].kind, "closed")
        self.assertTrue(session.closed)
        self.assertEqual(self.recognizer.stop_calls, 1)
        self.assertTrue(all(not getattr(self.recognizer, name).callbacks for name in
                            ("recognizing", "recognized", "session_started", "session_stopped", "canceled")))
        self.microphone.assert_not_called()

    def test_late_events_cannot_enter_a_closed_or_new_capture(self):
        first = self.start_capture()
        first.stop()
        first.drain()
        second = LiveSpeechSession(connection=TEST_CONNECTION, audio_config=object())
        first._on_final(recognition_event("Stale callback"))
        self.assertEqual(first.drain(), [])
        self.assertEqual(second.drain(), [])
        self.assertNotEqual(first.session_id, second.session_id)
        with self.assertRaisesRegex(LiveSpeechError, "cannot be restarted"):
            first.start()

    def test_cancellation_error_remains_visible_and_redacted(self):
        session = self.start_capture()
        self.recognizer.canceled.emit(SimpleNamespace(
            reason=speechsdk.CancellationReason.Error,
            error_code=speechsdk.CancellationErrorCode.AuthenticationFailure,
            error_details="401 " + TEST_CONNECTION.key + " Bearer private-test-token",
        ))
        self.assertTrue(session._closed.wait(2))
        errors = [event.text for event in session.drain() if event.kind == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("401", errors[0])
        self.assertNotIn(TEST_CONNECTION.key, errors[0])
        self.assertNotIn("private-test-token", errors[0])
        self.assertEqual(self.recognizer.stop_calls, 1)

    def test_normal_file_end_is_not_an_authentication_error(self):
        session = self.start_capture()
        self.recognizer.recognized.emit(recognition_event("File result."))
        self.recognizer.canceled.emit(SimpleNamespace(reason=speechsdk.CancellationReason.EndOfStream))
        self.assertTrue(session._closed.wait(2))
        events = session.drain()
        self.assertFalse(any(event.kind == "error" for event in events))
        self.assertTrue(any(event.text == "File result." for event in events))

    def test_stop_timeout_is_bounded_and_does_not_claim_shutdown(self):
        self.recognizer.stop_gate = threading.Event()
        self.addCleanup(self.recognizer.stop_gate.set)
        session = self.start_capture()
        with self.assertRaisesRegex(LiveSpeechError, "release is not yet confirmed"):
            session.stop(timeout=0.02)
        self.assertFalse(session.closed)
        self.assertTrue(session.stopping)
        self.recognizer.stop_gate.set()
        session.stop(timeout=2)
        self.assertTrue(session.closed)

    def test_stop_during_authentication_never_opens_the_microphone_later(self):
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def configure(*_args, **_kwargs):
            entered.set()
            release.wait(2)
            return SimpleNamespace(token_credential=None)

        self.configuration.side_effect = configure
        session = LiveSpeechSession(connection=TEST_CONNECTION)
        session.start()
        self.assertTrue(entered.wait(2))
        with self.assertRaises(LiveSpeechError):
            session.stop(timeout=0.01)
        release.set()
        session.stop(timeout=2)
        self.factory.assert_not_called()
        self.microphone.assert_not_called()

    def test_inactive_workspace_stops_capture(self):
        session = self.start_capture(inactivity_timeout=0.06)
        self.assertTrue(session._closed.wait(2))
        self.assertTrue(any("inactive" in event.text for event in session.drain()))
        self.assertEqual(self.recognizer.stop_calls, 1)

    def test_no_started_event_times_out_with_a_visible_error(self):
        self.recognizer.start_event_enabled = False
        session = self.start_capture(startup_timeout=0.06)
        self.assertTrue(session._closed.wait(2))
        self.assertTrue(any("startup timed out" in event.text for event in session.drain()))

    def test_native_stop_failure_is_not_reported_as_successful_cleanup(self):
        self.recognizer.stop_error = RuntimeError("Native stop failed")
        session = self.start_capture()
        with self.assertRaisesRegex(LiveSpeechError, "could not confirm microphone shutdown"):
            session.stop()
        self.assertTrue(session.cleanup_error)
        self.assertTrue(any(event.kind == "error" for event in session.drain()))
