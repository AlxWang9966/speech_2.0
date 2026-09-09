import json
import os
import unittest
from unittest.mock import patch

import httpx
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import CredentialUnavailableError

import speech_fast_transcription as speech
from tests.helpers import TEST_CONNECTION, UploadedAudio, payload, response, wav_audio


class ConnectionTests(unittest.TestCase):
    def test_existing_region_configuration_is_reused_for_both_engines(self):
        with patch.dict(os.environ, {"SPEECH_KEY": "test-key", "SPEECH_REGION": "eastus"}, clear=True):
            for engine in speech.ENGINE_LABELS:
                with self.subTest(engine=engine):
                    connection = speech.get_connection(engine)
                    self.assertEqual(connection.endpoint, "https://eastus.api.cognitive.microsoft.com")
                    self.assertEqual(connection.key, "test-key")
                    self.assertNotIn("test-key", repr(connection))
                    self.assertNotIn("key", connection.metadata())

    def test_custom_endpoint_and_separate_mai_credentials(self):
        environment = {
            "SPEECH_KEY": "original-key",
            "SPEECH_REGION": "eastus",
            "MAI_SPEECH_KEY": "other-key",
            "MAI_SPEECH_ENDPOINT": "https://other.cognitiveservices.azure.com/",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(speech.get_connection(speech.MAI_TRANSCRIBE).key, "other-key")
            self.assertEqual(speech.get_connection(speech.AZURE_FAST).key, "original-key")

    def test_partial_override_never_uses_another_resources_key_or_region(self):
        for partial in (
            {"MAI_SPEECH_ENDPOINT": "https://other.cognitiveservices.azure.com"},
            {"MAI_SPEECH_KEY": "other-key"},
            {"MAI_SPEECH_REGION": "westus"},
        ):
            with self.subTest(partial=list(partial)):
                with patch.dict(os.environ, {"SPEECH_KEY": "base", "SPEECH_REGION": "eastus", **partial}, clear=True):
                    with self.assertRaises(ValueError):
                        speech.get_connection(speech.MAI_TRANSCRIBE)

    def test_rejects_invalid_or_non_speech_endpoints(self):
        for endpoint in (
            "http://example.cognitiveservices.azure.com",
            "https://example.com",
            "https://example.openai.azure.com",
            "https://example.services.ai.azure.com/api/projects/demo",
            "https://example.cognitiveservices.azure.com/speechtotext",
            "https://example.cognitiveservices.azure.com?api-version=2025-10-15",
            "https://key@example.cognitiveservices.azure.com",
            "https://example.cognitiveservices.azure.com:8000",
        ):
            with self.subTest(endpoint=endpoint):
                with patch.dict(os.environ, {"SPEECH_KEY": "test", "SPEECH_ENDPOINT": endpoint}, clear=True):
                    with self.assertRaises(ValueError):
                        speech.get_connection(speech.MAI_TRANSCRIBE)

    def test_missing_configuration_and_unknown_engine(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "SPEECH_KEY"):
                speech.get_connection(speech.AZURE_FAST)
        with self.assertRaises(ValueError):
            speech.get_connection("unknown")

    def test_entra_uses_custom_endpoint_without_a_key(self):
        environment = {
            "SPEECH_AUTH_MODE": "entra",
            "SPEECH_ENDPOINT": TEST_CONNECTION.endpoint,
            "SPEECH_KEY": "inactive-key-must-not-be-used",
        }
        with patch.dict(os.environ, environment, clear=True):
            connection = speech.get_connection(speech.MAI_TRANSCRIBE)
        self.assertEqual(connection.auth_mode, "entra")
        self.assertIsNone(connection.key)
        self.assertEqual(connection.metadata()["auth_mode"], "entra")

    def test_entra_rejects_missing_or_regional_endpoint(self):
        for endpoint in ("", "https://eastus.api.cognitive.microsoft.com"):
            with self.subTest(endpoint=endpoint):
                with patch.dict(os.environ, {
                    "SPEECH_AUTH_MODE": "entra", "SPEECH_REGION": "eastus", "SPEECH_ENDPOINT": endpoint,
                }, clear=True):
                    with self.assertRaisesRegex(ValueError, "custom"):
                        speech.get_connection(speech.AZURE_FAST)

    def test_separate_entra_override_does_not_require_a_key(self):
        environment = {
            "SPEECH_KEY": "base-key", "SPEECH_REGION": "eastus",
            "MAI_SPEECH_AUTH_MODE": "entra", "MAI_SPEECH_ENDPOINT": TEST_CONNECTION.endpoint,
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(speech.get_connection(speech.AZURE_FAST).auth_mode, "key")
            self.assertEqual(speech.get_connection(speech.MAI_TRANSCRIBE).auth_mode, "entra")

    def test_unknown_auth_mode_is_not_silently_replaced_with_key_auth(self):
        with patch.dict(os.environ, {"SPEECH_AUTH_MODE": "unknown"}, clear=True):
            with self.assertRaisesRegex(ValueError, "AUTH_MODE"):
                speech.get_connection(speech.AZURE_FAST)


class DefinitionTests(unittest.TestCase):
    def test_mai_model_and_options_are_explicit(self):
        definition = speech.build_definition(
            speech.MAI_TRANSCRIBE,
            speech.TranscriptionOptions(locale="en-US", mai_style="clean", mai_timestamps="segment"),
        )
        self.assertEqual(definition["enhancedMode"], {
            "enabled": True,
            "model": "MAI-Transcribe-2",
            "modelOptions": {"transcribeStyle": "clean", "timestamps": "segment"},
        })
        self.assertEqual(definition["locales"], ["en"])
        self.assertEqual(definition["diarization"], {"enabled": True})
        self.assertNotIn("channels", definition)

    def test_mai_automatic_mode_omits_locales(self):
        definition = speech.build_definition(speech.MAI_TRANSCRIBE, speech.TranscriptionOptions())
        self.assertNotIn("locales", definition)
        self.assertEqual(len(speech.MAI_LANGUAGES), 60)

    def test_azure_defaults_preserve_candidates_without_mai_properties(self):
        definition = speech.build_definition(speech.AZURE_FAST, speech.TranscriptionOptions())
        self.assertEqual(definition["locales"], speech.LOCALES)
        self.assertEqual(definition["profanityFilterMode"], "Masked")
        self.assertNotIn("enhancedMode", definition)
        self.assertNotIn("diarizationSettings", definition)
        self.assertNotIn("wordLevelTimestampsEnabled", definition)
        self.assertNotIn("channels", definition)

    def test_invalid_settings_are_rejected(self):
        options = [
            speech.TranscriptionOptions(locale="invalid"),
            speech.TranscriptionOptions(mai_style="invalid"),
            speech.TranscriptionOptions(mai_timestamps="invalid"),
            speech.TranscriptionOptions(profanity_filter="invalid"),
        ]
        for value in options:
            with self.subTest(options=value):
                with self.assertRaises(ValueError):
                    speech.build_definition(speech.MAI_TRANSCRIBE, value)


class RequestTests(unittest.TestCase):
    @patch("speech_fast_transcription.AzureCliCredential")
    @patch("speech_fast_transcription.httpx.post")
    def test_entra_sends_only_bearer_authentication(self, post, credential):
        credential.return_value.get_token.return_value = AccessToken("unit-test-bearer", 9999999999)
        post.return_value = response()
        connection = speech.SpeechConnection(endpoint=TEST_CONNECTION.endpoint, auth_mode="entra")
        result = speech.transcribe_audio(b"audio", "sample.mp3", connection=connection)
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer unit-test-bearer"})
        credential.return_value.get_token.assert_called_once_with(speech.TOKEN_SCOPE)
        self.assertEqual(result.connection["auth_mode"], "entra")
        self.assertNotIn("unit-test-bearer", repr(result))

    @patch("speech_fast_transcription.AzureCliCredential")
    @patch("speech_fast_transcription.httpx.post")
    def test_entra_authentication_failure_never_sends_audio_or_falls_back(self, post, credential):
        connection = speech.SpeechConnection(endpoint=TEST_CONNECTION.endpoint, auth_mode="entra")
        for error in (ClientAuthenticationError("expired"), CredentialUnavailableError("CLI missing")):
            with self.subTest(error=type(error)):
                credential.return_value.get_token.side_effect = error
                with self.assertRaisesRegex(speech.TranscriptionError, "No transcription request was sent") as raised:
                    speech.transcribe_audio(b"audio", "sample.mp3", connection=connection)
                self.assertIsNone(raised.exception.request_seconds)
        post.assert_not_called()

    @patch("speech_fast_transcription.AzureCliCredential")
    @patch("speech_fast_transcription.httpx.post")
    def test_error_response_redacts_bearer_tokens(self, post, credential):
        credential.return_value.get_token.return_value = AccessToken("unit-test-bearer", 9999999999)
        post.return_value = response({"error": {"message": "Rejected unit-test-bearer"}}, 403)
        connection = speech.SpeechConnection(endpoint=TEST_CONNECTION.endpoint, auth_mode="entra")
        with self.assertRaises(speech.TranscriptionError) as raised:
            speech.transcribe_audio(b"audio", "sample.mp3", connection=connection)
        self.assertNotIn("unit-test-bearer", str(raised.exception))

    @patch("speech_fast_transcription.httpx.post")
    def test_request_contract_and_audio_duration(self, post):
        post.return_value = response()
        with patch("speech_fast_transcription.time.perf_counter", side_effect=[100, 102]):
            result = speech.transcribe_audio(
                wav_audio(), "original.wav", speech.MAI_TRANSCRIBE, connection=TEST_CONNECTION
            )
        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://unit-test.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15",
        )
        self.assertEqual(kwargs["headers"], {"Ocp-Apim-Subscription-Key": "unit-test-secret"})
        self.assertEqual(kwargs["timeout"].connect, 10)
        self.assertEqual(kwargs["timeout"].write, 300)
        self.assertEqual(kwargs["timeout"].read, 300)
        self.assertFalse(kwargs["follow_redirects"])
        self.assertEqual(kwargs["files"]["audio"], ("original.wav", wav_audio(), "audio/wav"))
        self.assertEqual(json.loads(kwargs["files"]["definition"][1])["enhancedMode"]["model"], "MAI-Transcribe-2")
        self.assertEqual(result.request_seconds, 2)
        self.assertEqual(result.audio_seconds, 4)
        self.assertEqual(result.duration_source, "WAV header")
        self.assertEqual(result.real_time_factor, 0.5)
        self.assertEqual(result.audio_speed, 2)
        self.assertEqual(result.text, "Hello world.")
        self.assertEqual(result.display_text, "Speaker 0: Hello world.")
        post.assert_called_once()
        post.return_value.close.assert_called_once()

    @patch("speech_fast_transcription.httpx.post")
    def test_original_filename_and_media_type_are_preserved(self, post):
        for name, mime in (("sample.MP3", "audio/mpeg"), ("sample.flac", "audio/flac"), ("sample.m4a", "audio/mp4")):
            with self.subTest(name=name):
                post.return_value = response()
                result = speech.transcribe_audio(b"encoded-audio", name, connection=TEST_CONNECTION)
                self.assertEqual(post.call_args.kwargs["files"]["audio"], (name, b"encoded-audio", mime))
                self.assertEqual(result.audio_seconds, 10)
                self.assertEqual(result.duration_source, "service durationMilliseconds")

    @patch("speech_fast_transcription.httpx.post")
    def test_disabled_diarization_does_not_display_default_speaker_ids(self, post):
        post.return_value = response()
        result = speech.transcribe_audio(
            b"audio", "sample.mp3", options=speech.TranscriptionOptions(diarization=False),
            connection=TEST_CONNECTION,
        )
        self.assertEqual(result.display_text, result.text)
        self.assertEqual(result.raw_response["phrases"][0]["speaker"], 0)

    @patch("speech_fast_transcription.httpx.post")
    def test_invalid_input_makes_no_requests(self, post):
        for data, name, engine in (
            (b"", "sample.wav", speech.AZURE_FAST),
            (b"audio", "sample.m4a", speech.MAI_TRANSCRIBE),
            (b"audio", "sample.txt", speech.AZURE_FAST),
        ):
            with self.subTest(name=name, engine=engine):
                with self.assertRaises(ValueError):
                    speech.transcribe_audio(data, name, engine, connection=TEST_CONNECTION)
        with patch("speech_fast_transcription.MAX_AUDIO_BYTES", 5):
            with self.assertRaises(ValueError):
                speech.transcribe_audio(b"12345", "sample.mp3", connection=TEST_CONNECTION)
        post.assert_not_called()

    @patch("speech_fast_transcription.httpx.post")
    def test_http_failures_are_not_retried_or_substituted(self, post):
        for status in (302, 400, 401, 403, 404, 413, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                post.reset_mock()
                post.return_value = response({"error": {"message": "Rejected unit-test-secret"}}, status)
                with self.assertRaises(speech.TranscriptionError) as raised:
                    speech.transcribe_audio(b"audio", "sample.mp3", speech.MAI_TRANSCRIBE, connection=TEST_CONNECTION)
                self.assertEqual(raised.exception.status_code, status)
                self.assertIsNotNone(raised.exception.request_seconds)
                self.assertNotIn(TEST_CONNECTION.key, str(raised.exception))
                post.assert_called_once()
                post.return_value.close.assert_called_once()

    @patch("speech_fast_transcription.httpx.post")
    def test_network_failures_have_elapsed_time_and_no_retry(self, post):
        for error in (
            httpx.WriteTimeout("upload stalled"),
            httpx.ReadTimeout("response stalled"),
            httpx.ConnectTimeout("connect timed out"),
            httpx.ConnectError("unavailable"),
            httpx.RemoteProtocolError("server closed the connection"),
        ):
            with self.subTest(error=type(error)):
                post.reset_mock()
                post.side_effect = error
                with self.assertRaises(speech.TranscriptionError) as raised:
                    speech.transcribe_audio(b"audio", "sample.mp3", connection=TEST_CONNECTION)
                self.assertIsNotNone(raised.exception.request_seconds)
                self.assertEqual(raised.exception.diagnostics["exception_type"], type(error).__name__)
                post.assert_called_once()

    @patch("speech_fast_transcription.httpx.post")
    def test_malformed_success_is_an_explicit_failure(self, post):
        for body in ([], {}, {"phrases": "invalid"}, {"phrases": [{"text": 12}]}):
            with self.subTest(body=body):
                post.return_value = response(body)
                with self.assertRaises(speech.TranscriptionError):
                    speech.transcribe_audio(b"audio", "sample.mp3", connection=TEST_CONNECTION)
        post.return_value = response()
        post.return_value.json.side_effect = ValueError("not JSON")
        with self.assertRaises(speech.TranscriptionError):
            speech.transcribe_audio(b"audio", "sample.mp3", connection=TEST_CONNECTION)

    @patch("speech_fast_transcription.get_connection", return_value=TEST_CONNECTION)
    @patch("speech_fast_transcription.httpx.post")
    def test_legacy_tuple_wrapper_retains_a_logged_diarization_fallback(self, post, _connection):
        post.side_effect = [response({"error": {"message": "diarization"}}, 400), response()]
        with self.assertLogs("speech_fast_transcription", level="INFO"):
            text, locale = speech.fast_transcript(UploadedAudio())
        self.assertEqual(text, "Hello world.")
        self.assertEqual(locale, "en-US")
        self.assertEqual(post.call_count, 2)
        definitions = [json.loads(call.kwargs["files"]["definition"][1]) for call in post.call_args_list]
        self.assertTrue(definitions[0]["diarization"]["enabled"])
        self.assertFalse(definitions[1]["diarization"]["enabled"])

    def test_httpx_multipart_wire_contract_and_independent_upload_timeout(self):
        audio = b"encoded-mp3-audio" * 1000

        def handler(request):
            body = request.read()
            self.assertIn(b'filename="sample.mp3"', body)
            self.assertIn(b"Content-Type: audio/mpeg", body)
            self.assertIn(audio, body)
            self.assertEqual(int(request.headers["Content-Length"]), len(body))
            self.assertEqual(request.extensions["timeout"]["connect"], 10)
            self.assertEqual(request.extensions["timeout"]["write"], 300)
            return httpx.Response(200, json=payload())

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with patch("speech_fast_transcription.httpx.post", side_effect=client.post):
                result = speech.transcribe_audio(audio, "sample.mp3", connection=TEST_CONNECTION)
        self.assertEqual(result.text, "Hello world.")

    @patch("speech_fast_transcription.httpx.post")
    def test_upload_timeouts_are_identified_and_diagnostics_redact_credentials(self, post):
        post.side_effect = httpx.WriteTimeout("write stalled unit-test-secret")
        with self.assertRaises(speech.TranscriptionError) as raised:
            speech.transcribe_audio(b"audio", "sample.mp3", connection=TEST_CONNECTION)
        error = raised.exception
        self.assertEqual(error.diagnostics["kind"], "upload_timeout")
        self.assertIn("upload", str(error))
        self.assertNotIn(TEST_CONNECTION.key, json.dumps(error.diagnostics))

    @patch("speech_fast_transcription.httpx.post")
    def test_503_retains_safe_request_diagnostics_and_retry_after(self, post):
        post.return_value = response({}, 503)
        post.return_value.json.side_effect = ValueError("not JSON")
        post.return_value.text = "Service unavailable: unit-test-secret"
        post.return_value.headers = {
            "apim-request-id": "request-123",
            "retry-after": "12",
            "set-cookie": "sensitive-cookie",
        }
        with patch("speech_fast_transcription.time.time", return_value=1000):
            with self.assertRaises(speech.TranscriptionError) as raised:
                speech.transcribe_audio(b"audio", "sample.mp3", connection=TEST_CONNECTION)
        details = raised.exception.diagnostics
        self.assertEqual(details["apim-request-id"], "request-123")
        self.assertEqual(details["retry_not_before"], 1012)
        self.assertNotIn("set-cookie", details)
        self.assertNotIn(TEST_CONNECTION.key, json.dumps(details))
        self.assertIn("temporarily unavailable", str(raised.exception))
        post.assert_called_once()

    def test_retry_after_http_date_and_invalid_header(self):
        http_response = response({}, 503)
        http_response.headers = {"retry-after": "Thu, 01 Jan 1970 00:20:00 GMT"}
        self.assertEqual(speech._response_diagnostics(http_response, "")["retry_not_before"], 1200)
        http_response.headers = {"retry-after": "invalid"}
        details = speech._response_diagnostics(http_response, "")
        self.assertIn("retry_after_parse_error", details)
        self.assertNotIn("retry_not_before", details)

    @patch("speech_fast_transcription.httpx.post")
    def test_nested_mai_diarization_error_is_actionable_without_silent_fallback(self, post):
        post.return_value = response({}, 503)
        post.return_value.json.side_effect = ValueError("not JSON")
        post.return_value.text = (
            'MAI service returned an error: ServiceUnavailable - '
            '{"error":{"code":"diarization_unavailable","message":"Diarization service returned error code 400"}}'
        )
        with self.assertRaises(speech.TranscriptionError) as raised:
            speech.transcribe_audio(b"audio", "sample.mp3", speech.MAI_TRANSCRIBE, connection=TEST_CONNECTION)
        self.assertEqual(raised.exception.diagnostics["service_code"], "diarization_unavailable")
        self.assertIn("speaker-diarization", str(raised.exception))
        self.assertTrue(json.loads(post.call_args.kwargs["files"]["definition"][1])["diarization"]["enabled"])
        post.assert_called_once()


class ResponseTests(unittest.TestCase):
    def test_combined_only_output_and_no_invented_language(self):
        text, display, locales, duration = speech.parse_transcription({
            "combinedPhrases": [{"text": "Recognized without timestamps"}],
        })
        self.assertEqual(text, display)
        self.assertEqual(locales, [])
        self.assertIsNone(duration)

    def test_silence_is_not_an_http_failure(self):
        text, display, locales, duration = speech.parse_transcription({
            "combinedPhrases": [{"text": ""}], "phrases": [], "durationMilliseconds": 2500,
        })
        self.assertEqual((text, display, locales, duration), ("", "", [], 2.5))

    def test_all_languages_and_speaker_zero_are_preserved(self):
        body = payload()
        body.pop("combinedPhrases")
        body["phrases"].append({"text": "Bonjour.", "speaker": 1, "locale": "fr-FR"})
        text, display, locales, _duration = speech.parse_transcription(body)
        self.assertEqual(text, "Hello world. Bonjour.")
        self.assertIn("Speaker 0:", display)
        self.assertIn("Speaker 1:", display)
        self.assertEqual(locales, ["en-US", "fr-FR"])

    def test_invalid_durations_are_rejected(self):
        for duration in (-1, float("nan"), float("inf"), True, "100"):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    speech.parse_transcription({"phrases": [], "durationMilliseconds": duration})
