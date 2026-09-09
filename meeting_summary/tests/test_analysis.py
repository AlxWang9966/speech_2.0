import base64
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import ClientAuthenticationError
import httpx
from openai import APITimeoutError, PermissionDeniedError
from PIL import Image

import llm_analysis as analysis
from service_errors import safe_error_text


def image_bytes(format="PNG", color="red"):
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, format=format)
    return buffer.getvalue()


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "GPT4o_API_KEY": "test-openai-key",
            "GPT4o_DEPLOYMENT_ENDPOINT": "https://original-unit-test.openai.azure.com/",
            "GPT4o_DEPLOYMENT_NAME": "test-deployment",
        }
        patch.dict(os.environ, self.environment, clear=True).start()
        self.factory = patch("llm_analysis.AzureOpenAI").start()
        self.client = self.factory.return_value.__enter__.return_value
        self.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content="A useful analysis."),
            )],
        )
        self.addCleanup(patch.stopall)

    def test_key_mode_preserves_existing_resource_and_deployment(self):
        self.assertEqual(analysis.call_openAI([]), "A useful analysis.")
        options = self.factory.call_args.kwargs
        self.assertEqual(options["azure_endpoint"], self.environment["GPT4o_DEPLOYMENT_ENDPOINT"].rstrip("/"))
        self.assertEqual(options["api_key"], "test-openai-key")
        self.assertEqual(options["max_retries"], 0)
        self.assertEqual(options["timeout"].read, 120)
        self.assertNotIn("azure_ad_token_provider", options)
        self.assertEqual(self.client.chat.completions.create.call_args.kwargs["model"], "test-deployment")

    @patch("llm_analysis.get_bearer_token_provider")
    @patch("llm_analysis.AzureCliCredential")
    def test_entra_uses_renewable_cli_provider_without_key_fallback(self, credential, provider):
        os.environ["GPT4o_AUTH_MODE"] = "entra"
        os.environ["AZURE_OPENAI_API_KEY"] = "ignored-alias-key"
        self.assertEqual(analysis.call_openAI([]), "A useful analysis.")
        provider.assert_called_once_with(credential.return_value, analysis.TOKEN_SCOPE)
        options = self.factory.call_args.kwargs
        self.assertEqual(options["api_key"], "")
        self.assertIs(options["azure_ad_token_provider"], provider.return_value)
        credential.return_value.close.assert_called_once()
        self.assertEqual(analysis.get_analysis_connection().key, "")

    def test_aliases_and_primary_precedence(self):
        with patch.dict(os.environ, {
            "AZURE_OPENAI_ENDPOINT": "https://alias.openai.azure.com",
            "AZURE_OPENAI_DEPLOYMENT": "alias-deployment",
            "AZURE_OPENAI_API_KEY": "alias-key",
            "AZURE_OPENAI_AUTH_MODE": "entra",
        }, clear=True):
            connection = analysis.get_analysis_connection()
            self.assertEqual(connection.auth_mode, "entra")
            self.assertEqual(connection.deployment, "alias-deployment")
            os.environ.update(self.environment)
            os.environ["GPT4o_AUTH_MODE"] = "key"
            connection = analysis.get_analysis_connection()
            self.assertEqual(connection.deployment, "test-deployment")
            self.assertEqual(connection.auth_mode, "key")

    def test_bad_mode_and_static_token_are_rejected(self):
        os.environ["GPT4o_AUTH_MODE"] = "auto"
        with self.assertRaisesRegex(ValueError, "must be key or entra"):
            analysis.call_openAI([])
        os.environ["GPT4o_AUTH_MODE"] = "key"
        os.environ["AZURE_OPENAI_AD_TOKEN"] = "ignored-static-token"
        with self.assertRaisesRegex(ValueError, "static token"):
            analysis.call_openAI([])
        self.factory.assert_not_called()

    def test_untrusted_endpoint_is_rejected_before_authentication(self):
        os.environ["GPT4o_DEPLOYMENT_ENDPOINT"] = "https://unit-test.invalid"
        with self.assertRaisesRegex(ValueError, "resource root"):
            analysis.call_openAI([])
        self.factory.assert_not_called()

    def test_key_policy_failure_is_actionable_and_does_not_expose_response_body(self):
        request = httpx.Request("POST", "https://unit-test.openai.azure.com")
        response = httpx.Response(403, request=request, headers={"x-request-id": "safe-request-id"})
        self.client.chat.completions.create.side_effect = PermissionDeniedError(
            "test-openai-key",
            response=response,
            body={"code": "AuthenticationTypeDisabled", "message": "test-openai-key"},
        )
        with self.assertRaises(analysis.AnalysisError) as error:
            analysis.call_openAI([])
        self.assertIn("GPT4o_AUTH_MODE=entra", str(error.exception))
        self.assertIn("403", str(error.exception))
        self.assertNotIn("test-openai-key", str(error.exception))
        self.assertEqual(self.factory.call_count, 1)

    def test_credential_failure_has_no_key_retry(self):
        self.client.chat.completions.create.side_effect = ClientAuthenticationError("credential details")
        with self.assertRaisesRegex(analysis.AnalysisError, "No key fallback"):
            analysis.call_openAI([])
        self.assertEqual(self.client.chat.completions.create.call_count, 1)

    def test_timeout_is_not_reported_as_success(self):
        self.client.chat.completions.create.side_effect = APITimeoutError(
            request=httpx.Request("POST", "https://unit-test.openai.azure.com"),
        )
        with self.assertRaisesRegex(analysis.AnalysisError, "processed and billed"):
            analysis.call_openAI([])

    def test_empty_and_truncated_outputs_are_not_successful(self):
        for choices in ([], [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=""))],
                        [SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="partial"))]):
            with self.subTest(choices=choices):
                self.client.chat.completions.create.return_value = SimpleNamespace(choices=choices)
                with self.assertRaises(analysis.AnalysisError):
                    analysis.call_openAI([])

    @patch("llm_analysis.call_openAI", return_value="image description")
    def test_each_supported_format_sends_its_actual_mime_and_unchanged_bytes(self, call):
        for format, mime in analysis.IMAGE_MIME_TYPES.items():
            with self.subTest(format=format):
                data = image_bytes(format)
                upload = io.BytesIO(data)
                upload.name = "misleading.png"
                analysis.analysis_image(upload, user_prompt="Name only the dominant color.")
                self.assertEqual(
                    call.call_args.args[0][1]["content"][0]["text"], "Name only the dominant color.",
                )
                url = call.call_args.args[0][1]["content"][1]["image_url"]["url"]
                prefix, encoded = url.split(",", 1)
                self.assertEqual(prefix, f"data:{mime};base64")
                self.assertEqual(base64.b64decode(encoded), data)

    def test_invalid_oversized_and_animated_images_fail_locally(self):
        with self.assertRaises(ValueError):
            analysis.image_mime_type(b"not an image")
        with patch("llm_analysis.MAX_IMAGE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "20 MB"):
                analysis.image_mime_type(image_bytes())
        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), "red").save(
            buffer, format="GIF", save_all=True, append_images=[Image.new("RGB", (16, 16), "blue")],
        )
        with self.assertRaisesRegex(ValueError, "Animated"):
            analysis.image_mime_type(buffer.getvalue())
        self.factory.assert_not_called()

    @patch("builtins.print")
    @patch("llm_analysis.call_openAI", return_value="private generated text")
    def test_analysis_does_not_print_private_results(self, _call, print_output):
        analysis.analysis_text("", "private transcript")
        analysis.analysis_image(io.BytesIO(image_bytes()))
        print_output.assert_not_called()

    def test_redaction_covers_environment_keys_and_unrecognized_tokens(self):
        text = safe_error_text("test-openai-key Bearer secret-token eyJabc.payload.signature", "separate-secret")
        self.assertNotIn("test-openai-key", text)
        self.assertNotIn("secret-token", text)
        self.assertNotIn("eyJabc", text)
