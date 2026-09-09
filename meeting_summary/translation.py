"""Post-stop text translation with explicit, resource-preserving authentication."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from azure.ai.translation.text import TextTranslationClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ServiceRequestError, ServiceResponseError
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

from service_errors import safe_error_text

load_dotenv(Path(__file__).resolve().parent / ".env")

GLOBAL_ENDPOINT = "https://api.cognitive.microsofttranslator.com"
TARGET_LANGUAGES = {
    "zh-CN": "zh-Hans",
    "en-US": "en",
    "ja-JP": "ja",
    "ko-KR": "ko",
    "fr-FR": "fr",
    "de-DE": "de",
    "es-ES": "es",
}
MAX_TRANSLATION_CHARACTERS = 50_000


class TranslationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranslationConnection:
    endpoint: str
    region: str
    auth_mode: str = "key"
    key: str = field(default="", repr=False)
    resource_id: str = ""


def get_translation_connection() -> TranslationConnection:
    mode = os.getenv("TRANSLATOR_AUTH_MODE", "key").strip().lower()
    endpoint = os.getenv("TRANSLATOR_ENDPOINT", GLOBAL_ENDPOINT).strip().rstrip("/")
    region = os.getenv("TRANSLATOR_REGION", "").strip().lower()
    key = os.getenv("TRANSLATOR_KEY", "").strip()
    resource_id = os.getenv("TRANSLATOR_RESOURCE_ID", "").strip().rstrip("/")
    if mode not in ("key", "entra"):
        raise ValueError("TRANSLATOR_AUTH_MODE must be key or entra.")
    if not region or not re.fullmatch(r"[a-z0-9]+", region):
        raise ValueError(
            "Set TRANSLATOR_REGION to the original Translator resource's region "
            "(or global for a global resource). It is never inferred from Speech."
        )
    if mode == "key" and not key:
        raise ValueError("Key-mode translation requires TRANSLATOR_KEY for the original Translator resource.")
    parsed = urlsplit(endpoint)
    is_global_endpoint = parsed.hostname == "api.cognitive.microsofttranslator.com"
    is_custom_endpoint = bool(parsed.hostname and parsed.hostname.endswith(".cognitiveservices.azure.com"))
    if (
        parsed.scheme != "https" or not (is_global_endpoint or is_custom_endpoint)
        or parsed.username or parsed.password or parsed.port not in (None, 443)
        or parsed.path or parsed.query or parsed.fragment
    ):
        raise ValueError(
            "TRANSLATOR_ENDPOINT must be the HTTPS global Translator endpoint or the "
            "original resource's custom cognitiveservices.azure.com root, without an API path."
        )
    if mode == "entra" and is_global_endpoint and not resource_id:
        raise ValueError(
            "Entra authentication on the global Translator endpoint requires "
            "TRANSLATOR_RESOURCE_ID for the original resource, plus TRANSLATOR_REGION."
        )
    if resource_id and not re.fullmatch(
        r"/subscriptions/[0-9a-f-]{36}/resourceGroups/[^/\s]+"
        r"/providers/Microsoft\.CognitiveServices/accounts/[^/\s]+",
        resource_id,
        re.IGNORECASE,
    ):
        raise ValueError("TRANSLATOR_RESOURCE_ID must be the original Translator's Azure resource ID.")
    return TranslationConnection(endpoint, region, mode, key if mode == "key" else "", resource_id)


def _translation_http_error(exc: HttpResponseError, connection: TranslationConnection) -> TranslationError:
    code = safe_error_text(getattr(exc.error, "code", None) or "Unknown", connection.key, limit=100)
    detail = safe_error_text(getattr(exc.error, "message", None) or "", connection.key)
    status = exc.status_code
    hint = "The Translator request failed. Check this resource's configuration and availability."
    if status in (401, 403):
        hint = (
            "Check the original Translator resource's authentication policy and data-plane access. "
            "If keys are disabled, use TRANSLATOR_AUTH_MODE=entra with an authorized az login; "
            "the global endpoint also needs TRANSLATOR_RESOURCE_ID and the original region. "
            "Do not change regions or enable keys to work around this."
        )
    elif status == 429:
        hint = "Translator is rate-limiting requests. Wait before explicitly trying again."
    elif status == 400:
        hint = "Check the target language, text length, and original Translator resource configuration."
    headers = exc.response.headers if exc.response is not None else {}
    request_id = safe_error_text(headers.get("x-requestid", headers.get("apim-request-id", "not returned")), connection.key, limit=100)
    retry_after = safe_error_text(headers.get("retry-after", ""), connection.key, limit=80)
    suffix = f" Retry-After: {retry_after}." if retry_after else ""
    return TranslationError(
        f"Translator HTTP {status} ({code}). {hint} {detail} "
        f"Request ID: {request_id}.{suffix} No automatic retry or authentication fallback was made."
    )


def translate_text(text: str, target_language: str, *, connection: TranslationConnection | None = None) -> str:
    if not text.strip():
        raise ValueError("There is no recognized text to translate.")
    if len(text) > MAX_TRANSLATION_CHARACTERS:
        raise ValueError("Translator accepts at most 50,000 characters per request. Use a shorter capture.")
    target = TARGET_LANGUAGES.get(target_language, target_language)
    if target not in TARGET_LANGUAGES.values():
        raise ValueError(f"Unsupported AVIA translation target: {target_language}")
    connection = connection or get_translation_connection()
    if connection.auth_mode == "entra":
        if connection.endpoint == GLOBAL_ENDPOINT and not (connection.resource_id and connection.region):
            raise ValueError("Global Translator Entra access requires the original resource ID and region.")
        credential = AzureCliCredential(process_timeout=30)
        auth = {}
        if connection.resource_id:
            auth = {"resource_id": connection.resource_id, "region": connection.region}
    elif connection.auth_mode == "key" and connection.key:
        credential = AzureKeyCredential(connection.key)
        auth = {"region": connection.region}
    else:
        raise ValueError("Translator requires the explicitly selected key or Entra configuration.")
    try:
        with TextTranslationClient(
            endpoint=connection.endpoint,
            credential=credential,
            retry_total=0,
            connection_timeout=10,
            read_timeout=60,
            **auth,
        ) as client:
            result = client.translate(body=[text], to_language=[target])
    except ClientAuthenticationError as exc:
        if exc.status_code is not None:
            raise _translation_http_error(exc, connection) from exc
        raise TranslationError(
            "Translator Entra sign-in failed. Install Azure CLI and run az login with the "
            "identity authorized for the original Translator resource. No key fallback was made."
        ) from exc
    except HttpResponseError as exc:
        raise _translation_http_error(exc, connection) from exc
    except (ServiceRequestError, ServiceResponseError) as exc:
        raise TranslationError(
            "Translator connection or response failed. Check access to the configured endpoint. "
            "This request may have been processed; no automatic retry was made."
        ) from exc
    finally:
        if connection.auth_mode == "entra":
            credential.close()
    if (
        not result or len(result) != 1 or not result[0].translations
        or not isinstance(result[0].translations[0].text, str)
        or not result[0].translations[0].text.strip()
    ):
        raise TranslationError("Translator returned no translated text. The transcript is unchanged.")
    return result[0].translations[0].text
