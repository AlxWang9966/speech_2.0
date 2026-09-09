import os
from dataclasses import asdict, make_dataclass
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import llm_analysis
from tests.helpers import TEST_CONNECTION, UploadedAudio, payload, response

APP = Path(__file__).resolve().parents[1] / "meeting_sum.py"


class AppTests(unittest.TestCase):
    def setUp(self):
        environment = {
            name: value for name, value in os.environ.items()
            if not name.startswith(("SPEECH_", "MAI_SPEECH_", "GPT4o_", "AZURE_OPENAI_"))
        }
        environment.update({"SPEECH_KEY": "unit-test", "SPEECH_REGION": "eastus"})
        patch.dict(os.environ, environment, clear=True).start()
        patch("dotenv.load_dotenv", return_value=False).start()
        self.post = patch("speech_fast_transcription.httpx.post", return_value=response()).start()
        self.addCleanup(patch.stopall)

    def open_lab(self):
        app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(app.exception)
        app.button(key="open_audio_file_summary").click().run()
        self.assertFalse(app.exception)
        return app

    def test_home_and_lab_do_not_require_openai_credentials(self):
        app = self.open_lab()
        self.assertEqual(app.radio(key="audio_engine_mode").value, "Azure Fast")
        self.assertTrue(app.button(key="audio_run").disabled)
        self.post.assert_not_called()

    def test_missing_speech_configuration_disables_submission_without_crashing(self):
        with patch.dict(os.environ, {"SPEECH_KEY": "", "SPEECH_REGION": ""}):
            app = self.open_lab()
        self.assertTrue(app.button(key="audio_run").disabled)
        self.assertTrue(any("SPEECH_KEY" in warning.value for warning in app.warning))
        self.post.assert_not_called()

    def test_entra_configuration_does_not_require_a_speech_key(self):
        with patch.dict(os.environ, {
            "SPEECH_AUTH_MODE": "entra",
            "SPEECH_ENDPOINT": TEST_CONNECTION.endpoint,
            "SPEECH_KEY": "",
        }):
            app = self.open_lab()
        self.assertFalse(app.exception)
        self.assertFalse(any("SPEECH_KEY" in warning.value for warning in app.warning))
        self.post.assert_not_called()

    @patch("streamlit.file_uploader", return_value=UploadedAudio())
    def test_results_persist_without_retranscribing_on_rerun(self, _upload):
        app = self.open_lab()
        app.button(key="audio_run").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.post.call_count, 1)
        self.assertTrue(any("Speaker 0: Hello world." in area.value for area in app.text_area))
        self.assertTrue(any("Accuracy not scored" in info.value for info in app.info))
        app.checkbox(key="audio_diarization").set_value(False).run()
        self.assertFalse(app.exception)
        self.assertEqual(self.post.call_count, 1)
        self.assertTrue(any("Inputs have changed" in warning.value for warning in app.warning))

    @patch("streamlit.file_uploader", return_value=UploadedAudio())
    def test_a_new_run_replaces_displayed_transcripts(self, _upload):
        app = self.open_lab()
        app.button(key="audio_run").click().run()
        self.post.return_value = response(payload("A different transcript."))
        app.button(key="audio_run").click().run()
        self.assertFalse(app.exception)
        transcripts = [area.value for area in app.text_area if area.label == "Transcript"]
        self.assertEqual(transcripts, ["Speaker 0: A different transcript."])
        self.assertEqual(self.post.call_count, 2)

    @patch("streamlit.file_uploader", return_value=UploadedAudio())
    def test_compare_preserves_success_and_shows_other_engine_failure(self, _upload):
        app = self.open_lab()
        app.radio(key="audio_engine_mode").set_value("Compare both").run()
        self.post.side_effect = [response(), response({"error": {"message": "Model unavailable"}}, 403)]
        app.button(key="audio_run").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.post.call_count, 2)
        self.assertTrue(any("HTTP 403" in error.value for error in app.error))
        self.assertTrue(any("Hello world." in area.value for area in app.text_area))

    @patch("streamlit.file_uploader", return_value=UploadedAudio())
    def test_explicit_retry_recovers_only_failed_engine_and_preserves_success(self, _upload):
        app = self.open_lab()
        app.radio(key="audio_engine_mode").set_value("Compare both").run()
        self.post.side_effect = [
            response(), response({"error": {"message": "Busy"}}, 503),
            response(payload("Recovered transcript.")),
        ]
        app.button(key="audio_run").click().run()
        self.assertEqual(self.post.call_count, 2)
        app.button(key="audio_retry").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.post.call_count, 3)
        self.assertFalse(app.error)
        transcripts = [area.value for area in app.text_area if area.label == "Transcript"]
        self.assertIn("Speaker 0: Hello world.", transcripts)
        self.assertIn("Speaker 0: Recovered transcript.", transcripts)
        self.assertEqual(len(app.session_state["audio_report"].runs), 3)

    @patch("streamlit.file_uploader", return_value=UploadedAudio())
    def test_changed_settings_require_a_new_run_not_a_retry(self, _upload):
        self.post.return_value = response({"error": {"message": "Busy"}}, 503)
        app = self.open_lab()
        app.button(key="audio_run").click().run()
        app.checkbox(key="audio_diarization").set_value(False).run()
        self.assertTrue(app.button(key="audio_retry").disabled)
        self.assertEqual(self.post.call_count, 1)

    @patch("streamlit.file_uploader", return_value=UploadedAudio())
    def test_equivalent_settings_from_before_code_reload_can_be_retried(self, _upload):
        self.post.return_value = response({"error": {"message": "Busy"}}, 503)
        app = self.open_lab()
        app.button(key="audio_run").click().run()
        report = app.session_state["audio_report"]
        values = asdict(report.options)
        previous_options = make_dataclass("PreviousOptions", [(name, object) for name in values])
        report.options = previous_options(**values)
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.button(key="audio_retry").disabled)
        self.assertEqual(self.post.call_count, 1)

    @patch("streamlit.file_uploader", return_value=UploadedAudio("sample.m4a"))
    def test_mai_m4a_is_rejected_before_any_request(self, _upload):
        app = self.open_lab()
        app.radio(key="audio_engine_mode").set_value("MAI-Transcribe-2 (preview)").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key="audio_run").disabled)
        self.assertTrue(any("Convert the audio file" in warning.value for warning in app.warning))
        self.post.assert_not_called()

    @patch("llm_analysis.analysis_text", return_value="A separate summary.")
    @patch("streamlit.file_uploader", return_value=UploadedAudio())
    def test_summary_is_explicit_and_does_not_rerun_transcription(self, _upload, summarize):
        app = self.open_lab()
        app.text_area(key="audio_reference").set_value("Hello world.").run()
        app.button(key="audio_run").click().run()
        self.assertFalse(app.exception)
        summarize.assert_not_called()
        app.button(key="audio_generate_summary").click().run()
        self.assertFalse(app.exception)
        summarize.assert_called_once()
        self.assertEqual(self.post.call_count, 1)
        self.assertTrue(any("A separate summary." in markdown.value for markdown in app.markdown))


class OptionalAnalysisTests(unittest.TestCase):
    def test_missing_openai_configuration_has_an_actionable_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Transcription does not require Azure OpenAI"):
                llm_analysis.call_openAI([])

    @patch("llm_analysis.call_openAI", return_value="summary")
    def test_mai_language_codes_use_the_existing_language_prompts(self, call):
        llm_analysis.analysis_text("", "bonjour", "fr")
        self.assertIn("fran", call.call_args.args[0][1]["content"][0]["text"])

    @patch("llm_analysis.call_openAI", return_value="summary")
    def test_other_mai_languages_do_not_force_an_english_summary(self, call):
        llm_analysis.analysis_text("", "test", "vi")
        self.assertIn("same language", call.call_args.args[0][1]["content"][0]["text"])
