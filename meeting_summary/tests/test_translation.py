import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ServiceRequestError

import translation

RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/unit-test"
    "/providers/Microsoft.CognitiveServices/accounts/original-translator"
)


class TranslationTests(unittest.TestCase):
    def setUp(self):
        patch.dict(os.environ, {
            "TRANSLATOR_ENDPOINT": translation.GLOBAL_ENDPOINT + "/",
            "TRANSLATOR_REGION": "eastasia",
            "TRANSLATOR_KEY": "original-test-key",
            "SPEECH_REGION": "eastus",
        }, clear=True).start()
        self.factory = patch("translation.TextTranslationClient").start()
        self.client = self.factory.return_value.__enter__.return_value
        self.client.translate.return_value = [
            SimpleNamespace(translations=[SimpleNamespace(text="Translated text.", to="zh-Hans")]),
        ]
        self.addCleanup(patch.stopall)

    def test_key_mode_keeps_original_region_and_global_endpoint(self):
        self.assertEqual(translation.translate_text("Hello.", "zh-CN"), "Translated text.")
        options = self.factory.call_args.kwargs
        self.assertEqual(options["region"], "eastasia")
        self.assertEqual(options["endpoint"], translation.GLOBAL_ENDPOINT)
        self.assertEqual(options["credential"].key, "original-test-key")
        self.assertEqual(options["retry_total"], 0)
        self.assertEqual(options["connection_timeout"], 10)
        self.assertEqual(options["read_timeout"], 60)
        self.client.translate.assert_called_once_with(body=["Hello."], to_language=["zh-Hans"])

    @patch("translation.AzureCliCredential")
    def test_global_entra_uses_same_resource_region_and_never_the_old_key(self, credential):
        os.environ.update({"TRANSLATOR_AUTH_MODE": "entra", "TRANSLATOR_RESOURCE_ID": RESOURCE_ID})
        translation.translate_text("Hello.", "zh-CN")
        options = self.factory.call_args.kwargs
        self.assertIs(options["credential"], credential.return_value)
        self.assertEqual(options["resource_id"], RESOURCE_ID)
        self.assertEqual(options["region"], "eastasia")
        self.assertEqual(options["endpoint"], translation.GLOBAL_ENDPOINT)
        self.assertEqual(translation.get_translation_connection().key, "")
        self.assertNotIn("original-test-key", repr(options))
        credential.return_value.close.assert_called_once()

    @patch("translation.AzureCliCredential")
    def test_custom_entra_endpoint_does_not_send_incomplete_regional_sdk_auth(self, _credential):
        os.environ.update({
            "TRANSLATOR_AUTH_MODE": "entra",
            "TRANSLATOR_ENDPOINT": "https://original-translator.cognitiveservices.azure.com/",
        })
        translation.translate_text("Hello.", "en-US")
        options = self.factory.call_args.kwargs
        self.assertNotIn("region", options)
        self.assertNotIn("resource_id", options)
        self.assertEqual(options["endpoint"], "https://original-translator.cognitiveservices.azure.com")

    def test_global_entra_requires_original_resource_id_before_any_request(self):
        os.environ["TRANSLATOR_AUTH_MODE"] = "entra"
        with self.assertRaisesRegex(ValueError, "TRANSLATOR_RESOURCE_ID"):
            translation.translate_text("Hello.", "zh-CN")
        self.factory.assert_not_called()

    def test_missing_translator_region_is_not_inferred_from_speech(self):
        del os.environ["TRANSLATOR_REGION"]
        with self.assertRaisesRegex(ValueError, "never inferred from Speech"):
            translation.translate_text("Hello.", "zh-CN")
        self.factory.assert_not_called()

    def test_invalid_mode_endpoint_and_resource_id_are_rejected(self):
        for name, value in (
            ("TRANSLATOR_AUTH_MODE", "automatic"),
            ("TRANSLATOR_ENDPOINT", "https://unknown.example/"),
            ("TRANSLATOR_ENDPOINT", translation.GLOBAL_ENDPOINT + "/translate"),
            ("TRANSLATOR_RESOURCE_ID", "wrong"),
        ):
            with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                with self.assertRaises(ValueError):
                    translation.translate_text("Hello.", "zh-CN")
        self.factory.assert_not_called()

    def test_target_locales_are_mapped_to_translator_codes(self):
        for locale, expected in translation.TARGET_LANGUAGES.items():
            with self.subTest(locale=locale):
                translation.translate_text("Hello.", locale)
                self.assertEqual(self.client.translate.call_args.kwargs["to_language"], [expected])

    def test_empty_large_or_unsupported_input_fails_locally(self):
        for text, target in ((" ", "zh-CN"), ("x" * 50001, "zh-CN"), ("hello", "invalid")):
            with self.subTest(target=target, size=len(text)):
                with self.assertRaises(ValueError):
                    translation.translate_text(text, target)
        self.factory.assert_not_called()

    def test_empty_translation_is_an_error_not_a_transcript_replacement(self):
        for result in ([], [SimpleNamespace(translations=[])],
                       [SimpleNamespace(translations=[SimpleNamespace(text="")])]):
            with self.subTest(result=result):
                self.client.translate.return_value = result
                with self.assertRaisesRegex(translation.TranslationError, "no translated text"):
                    translation.translate_text("Hello.", "zh-CN")

    def test_policy_error_preserves_status_and_redacts_credentials(self):
        response = Mock(status_code=403, reason="Forbidden", headers={"x-requestid": "safe-id"})
        error = HttpResponseError(
            message="Original resource error", response=response,
        )
        error.error = SimpleNamespace(
            code="AuthenticationTypeDisabled", message="Key original-test-key and Bearer private-token are disabled.",
        )
        self.client.translate.side_effect = error
        with self.assertRaises(translation.TranslationError) as caught:
            translation.translate_text("Hello.", "zh-CN")
        message = str(caught.exception)
        self.assertIn("403", message)
        self.assertIn("AuthenticationTypeDisabled", message)
        self.assertIn("TRANSLATOR_AUTH_MODE=entra", message)
        self.assertNotIn("original-test-key", message)
        self.assertNotIn("private-token", message)
        self.assertEqual(self.client.translate.call_count, 1)

    def test_credential_and_network_errors_do_not_fall_back(self):
        for error in (ClientAuthenticationError(message="not logged in"), ServiceRequestError("network failure")):
            with self.subTest(error=type(error).__name__):
                self.client.translate.side_effect = error
                self.client.translate.reset_mock()
                with self.assertRaises(translation.TranslationError):
                    translation.translate_text("Hello.", "zh-CN")
                self.assertEqual(self.client.translate.call_count, 1)
