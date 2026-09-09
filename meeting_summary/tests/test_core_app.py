import io
import os
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from llm_analysis import AnalysisError
from speech_streaming import LiveSpeechError, SpeechEvent
from tests.test_analysis import image_bytes
from translation import TranslationError

APP = Path(__file__).resolve().parents[1] / "meeting_sum.py"


class UploadedImage(io.BytesIO):
    def __init__(self, data=None, name="sample.png"):
        super().__init__(image_bytes() if data is None else data)
        self.name = name


class FakeLiveSession:
    def __init__(self, **_kwargs):
        self.session_id = uuid4().hex
        self.closed = False
        self.stopping = False
        self.cleanup_error = ""
        self.stop_calls = 0
        self.stop_error = False
        self.events = []

    def start(self):
        self.events.append(SpeechEvent(self.session_id, "started"))

    def touch(self):
        pass

    def drain(self):
        result, self.events = self.events, []
        return result

    def stop(self):
        self.stop_calls += 1
        if self.stop_error:
            raise LiveSpeechError("Speech is still stopping; release is not yet confirmed.")
        if not self.closed:
            self.events.extend([
                SpeechEvent(self.session_id, "final", "Tail received during Stop."),
                SpeechEvent(self.session_id, "closed"),
            ])
        self.closed = True


class CoreAppTests(unittest.TestCase):
    def setUp(self):
        environment = {
            name: value for name, value in os.environ.items()
            if not name.startswith(("SPEECH_", "MAI_SPEECH_", "GPT4o_", "AZURE_OPENAI_", "TRANSLATOR_"))
        }
        environment.update({
            "SPEECH_KEY": "test-key", "SPEECH_REGION": "eastus",
            "TRANSLATOR_KEY": "test-translator", "TRANSLATOR_REGION": "eastasia",
        })
        patch.dict(os.environ, environment, clear=True).start()
        patch("dotenv.load_dotenv", return_value=False).start()
        self.addCleanup(patch.stopall)

    def open_workspace(self, name):
        app = AppTest.from_file(str(APP), default_timeout=15).run()
        app.button(key="open_" + name).click().run()
        self.assertFalse(app.exception)
        return app

    @patch("llm_analysis.analysis_image", return_value="Saved image description.")
    @patch("streamlit.file_uploader", return_value=UploadedImage())
    def test_image_result_and_download_survive_reruns_and_prompt_changes(self, _upload, analyze):
        app = self.open_workspace("image_analysis")
        prompt = "Name only the dominant color in English."
        app.text_area(key="image_prompt").set_value(prompt).run()
        app.button(key="image_analyze").click().run()
        self.assertFalse(app.exception)
        analyze.assert_called_once_with(_upload.return_value, user_prompt=prompt)
        self.assertEqual(app.session_state["image_analysis_result"]["prompt"], prompt)
        app.run()
        self.assertEqual(analyze.call_count, 1)
        self.assertTrue(any(item.value == "Saved image description." for item in app.markdown))
        self.assertTrue(any(
            item.proto.label == "Download Result" and item.proto.url
            for item in app.get("download_button")
        ))
        app.text_area(key="image_prompt").set_value("Changed prompt").run()
        self.assertTrue(any("Inputs have changed" in item.value for item in app.warning))
        self.assertEqual(analyze.call_count, 1)

    @patch("llm_analysis.analysis_image", side_effect=["Earlier analysis.", AnalysisError("Original resource denied access")])
    @patch("streamlit.file_uploader", return_value=UploadedImage())
    def test_image_error_is_persistent_and_does_not_erase_an_earlier_result(self, _upload, analyze):
        app = self.open_workspace("image_analysis")
        app.button(key="image_analyze").click().run()
        app.button(key="image_analyze").click().run()
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(analyze.call_count, 2)
        self.assertTrue(any("denied access" in item.value for item in app.error))
        self.assertTrue(any(item.value == "Earlier analysis." for item in app.markdown))

    @patch("streamlit.file_uploader", return_value=UploadedImage(b"invalid"))
    def test_invalid_image_disables_analysis_without_crashing_preview(self, _upload):
        app = self.open_workspace("image_analysis")
        self.assertTrue(app.button(key="image_analyze").disabled)
        self.assertTrue(app.warning)

    @patch("scenarios.live_mic.LiveSpeechSession", side_effect=FakeLiveSession)
    def test_stop_preserves_final_tail_and_back_stops_capture(self, factory):
        app = self.open_workspace("live_mic")
        app.button(key="live_start").click().run()
        session = app.session_state["live_session"]
        app.run()
        self.assertTrue(app.button(key="live_start").disabled)
        app.button(key="live_stop").click().run()
        self.assertTrue(session.closed)
        self.assertIn("Tail received during Stop.", app.session_state["live_segments"])
        app.button(key="live_start").click().run()
        second = app.session_state["live_session"]
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(second.closed)
        self.assertIsNone(app.session_state["selected_scenario"])
        self.assertEqual(factory.call_count, 2)

    @patch("scenarios.live_mic.LiveSpeechSession", side_effect=FakeLiveSession)
    def test_clear_stops_before_discarding_and_ignores_old_callbacks(self, _factory):
        app = self.open_workspace("live_mic")
        app.button(key="live_start").click().run()
        old = app.session_state["live_session"]
        app.button(key="live_clear").click().run()
        self.assertTrue(old.closed)
        self.assertEqual(app.session_state["live_segments"], [])
        app.button(key="live_start").click().run()
        old.events.append(SpeechEvent(old.session_id, "final", "Stale old caption"))
        app.run()
        self.assertNotIn("Stale old caption", app.session_state["live_segments"])

    @patch("scenarios.live_mic.LiveSpeechSession", side_effect=FakeLiveSession)
    def test_stop_failure_blocks_clear_and_back_without_losing_transcript(self, _factory):
        app = self.open_workspace("live_mic")
        app.button(key="live_start").click().run()
        session = app.session_state["live_session"]
        session.stop_error = True
        session.events.append(SpeechEvent(session.session_id, "final", "Keep this caption"))
        app.button(key="live_clear").click().run()
        self.assertEqual(app.session_state["live_segments"], ["Keep this caption"])
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["selected_scenario"], "live_mic")
        self.assertTrue(app.error)
        self.assertFalse(session.closed)

    @patch("scenarios.live_mic.translate_text", return_value="Translation of all final sentences.")
    @patch("scenarios.live_mic.LiveSpeechSession", side_effect=FakeLiveSession)
    def test_translation_is_only_after_stop_and_does_not_repeat_on_refresh(self, _factory, translate):
        app = self.open_workspace("live_mic")
        app.checkbox(key="live_translate_enabled").set_value(True).run()
        app.button(key="live_start").click().run()
        translate.assert_not_called()
        app.run()
        app.button(key="live_stop").click().run()
        self.assertFalse(app.exception)
        translate.assert_called_once_with("Tail received during Stop.", "zh-CN")
        app.run()
        self.assertEqual(translate.call_count, 1)
        self.assertEqual(app.session_state["live_translation"]["text"], "Translation of all final sentences.")
        app.selectbox(key="live_target_lang").set_value("ja-JP").run()
        self.assertTrue(any("earlier transcript or target language" in item.value for item in app.warning))

    @patch("scenarios.live_mic.translate_text", side_effect=TranslationError("Translator HTTP 403. Entra required."))
    @patch("scenarios.live_mic.LiveSpeechSession", side_effect=FakeLiveSession)
    def test_translation_failure_is_not_a_success_shaped_result_or_automatic_retry(self, _factory, translate):
        app = self.open_workspace("live_mic")
        app.checkbox(key="live_translate_enabled").set_value(True).run()
        app.button(key="live_start").click().run()
        app.run()
        app.button(key="live_stop").click().run()
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(translate.call_count, 1)
        self.assertIsNone(app.session_state["live_translation"])
        self.assertTrue(any("Translator HTTP 403" in item.value for item in app.error))
        self.assertIn("Tail received during Stop.", app.session_state["live_segments"])

    @patch("scenarios.live_mic.LiveSpeechSession", side_effect=FakeLiveSession)
    def test_service_text_is_displayed_literally_not_injected_as_html(self, _factory):
        app = self.open_workspace("live_mic")
        app.button(key="live_start").click().run()
        session = app.session_state["live_session"]
        text = "<script>alert('caption')</script>"
        session.events.append(SpeechEvent(session.session_id, "final", text))
        session.events.append(SpeechEvent(session.session_id, "error", "Speech HTTP 401"))
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(text == item.value for item in app.text))
        self.assertFalse(any(text in item.value for item in app.markdown))
        self.assertTrue(any("Speech HTTP 401" in item.value for item in app.error))

    def test_live_workspace_does_not_construct_a_microphone_until_start(self):
        with patch("speech_streaming.speechsdk.audio.AudioConfig") as microphone:
            app = self.open_workspace("live_mic")
            app.run()
            microphone.assert_not_called()
