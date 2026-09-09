import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import presentation as ui
from tests.helpers import UploadedAudio, response
from tests.test_core_app import FakeLiveSession

APP = Path(__file__).resolve().parents[1] / "meeting_sum.py"


class PresentationTests(unittest.TestCase):
    def setUp(self):
        environment = {
            name: value for name, value in os.environ.items()
            if not name.startswith(("SPEECH_", "MAI_SPEECH_", "GPT4o_", "AZURE_OPENAI_", "TRANSLATOR_"))
        }
        environment.update({"SPEECH_KEY": "test-key", "SPEECH_REGION": "eastus"})
        patch.dict(os.environ, environment, clear=True).start()
        patch("dotenv.load_dotenv", return_value=False).start()
        self.addCleanup(patch.stopall)

    def app(self):
        app = AppTest.from_file(str(APP), default_timeout=15).run()
        self.assertFalse(app.exception)
        return app

    @patch("presentation.st.html")
    def test_theme_control_uses_both_palettes_without_javascript_dependency(self, render):
        for theme in ("Light", "Dark"):
            with self.subTest(theme=theme):
                ui.apply_theme(theme)
                html = render.call_args.args[0]
                self.assertIn(f'data-avia-theme="{theme.lower()}"', html)
                self.assertIn('--cp-accent: #b11f4b;', html)
                self.assertIn('--cp-accent: #fd8ea1;', html)
                self.assertIn('html:has([data-avia-theme="dark"])', html)
                self.assertIn("@container avia-main", html)
        with self.assertRaises(ValueError):
            ui.apply_theme("unsupported")

    @patch("presentation.st.html")
    def test_dynamic_presentation_text_is_escaped(self, render):
        ui.metric_card("<script>caption</script>", "<img src=x>", "<b>Not HTML</b>")
        html = render.call_args.args[0]
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;b&gt;Not HTML&lt;/b&gt;", html)

    def test_home_call_to_action_and_sidebar_open_the_same_lab(self):
        app = self.app()
        app.button(key="hero_open_lab").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["selected_scenario"], "audio_file_summary")
        self.assertEqual(app.radio(key="audio_engine_mode").value, "Azure Fast")
        app.button(key="back_to_scenarios").click().run()
        app.button(key="nav_audio_file_summary").click().run()
        self.assertEqual(app.session_state["selected_scenario"], "audio_file_summary")
        self.assertFalse(app.exception)

    def test_workspace_launch_buttons_use_the_same_neutral_variant(self):
        app = self.app()
        for key in ui.WORKSPACES:
            with self.subTest(workspace=key):
                self.assertEqual(app.button(key=f"open_{key}").proto.type, "secondary")

    @patch("scenarios.live_mic.LiveSpeechSession", side_effect=FakeLiveSession)
    def test_appearance_changes_do_not_restart_or_stop_live_capture(self, factory):
        app = self.app()
        app.button(key="nav_live_mic").click().run()
        app.button(key="live_start").click().run()
        session = app.session_state["live_session"]
        app.radio(key="avia_appearance").set_value("Dark").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["live_session"].session_id, session.session_id)
        self.assertEqual(session.stop_calls, 0)
        self.assertEqual(factory.call_count, 1)
        app.button(key="nav_image_analysis").click().run()
        self.assertTrue(session.closed)
        self.assertEqual(app.session_state["selected_scenario"], "image_analysis")
        self.assertEqual(app.radio(key="avia_appearance").value, "Dark")

    @patch("scenarios.live_mic.LiveSpeechSession", side_effect=FakeLiveSession)
    def test_sidebar_cannot_leave_capture_after_shutdown_failure(self, _factory):
        app = self.app()
        app.button(key="nav_live_mic").click().run()
        app.button(key="live_start").click().run()
        session = app.session_state["live_session"]
        session.stop_error = True
        app.button(key="nav_audio_file_summary").click().run()
        self.assertEqual(app.session_state["selected_scenario"], "live_mic")
        self.assertTrue(app.error)
        self.assertFalse(session.closed)

    @patch("streamlit.file_uploader", return_value=UploadedAudio())
    @patch("speech_fast_transcription.httpx.post", return_value=response())
    def test_theme_switch_preserves_measured_report_without_new_requests(self, post, _upload):
        app = self.app()
        app.button(key="open_audio_file_summary").click().run()
        app.button(key="audio_run").click().run()
        report_json = app.session_state["audio_report"].to_json()
        for theme in ("Dark", "Light"):
            app.radio(key="avia_appearance").set_value(theme).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["audio_report"].to_json(), report_json)
        post.assert_called_once()
