import base64
from dataclasses import dataclass, field
import io
import os
from pathlib import Path
from urllib.parse import urlsplit
import warnings

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, get_bearer_token_provider
from dotenv import load_dotenv
import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AzureOpenAI
from PIL import Image, UnidentifiedImageError

from service_errors import safe_error_text

load_dotenv(Path(__file__).resolve().parent / ".env")

TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
ANALYSIS_TIMEOUT = httpx.Timeout(connect=10.0, write=60.0, read=120.0, pool=10.0)
MAX_IMAGE_BYTES = 20_000_000
IMAGE_MIME_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


class AnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnalysisConnection:
    endpoint: str
    deployment: str
    auth_mode: str = "key"
    key: str = field(default="", repr=False)
    api_version: str = "2024-02-01"


def _setting(primary: str, alias: str, default: str = "") -> str:
    return os.getenv(primary, "").strip() or os.getenv(alias, "").strip() or default


def get_analysis_connection() -> AnalysisConnection:
    endpoint = _setting("GPT4o_DEPLOYMENT_ENDPOINT", "AZURE_OPENAI_ENDPOINT").rstrip("/")
    deployment = _setting("GPT4o_DEPLOYMENT_NAME", "AZURE_OPENAI_DEPLOYMENT")
    key = _setting("GPT4o_API_KEY", "AZURE_OPENAI_API_KEY")
    mode = _setting("GPT4o_AUTH_MODE", "AZURE_OPENAI_AUTH_MODE", "key").lower()
    if mode not in ("key", "entra"):
        raise ValueError("GPT4o_AUTH_MODE (or AZURE_OPENAI_AUTH_MODE) must be key or entra.")
    if not endpoint or not deployment or (mode == "key" and not key):
        raise ValueError(
            "Summaries and image analysis require GPT4o_DEPLOYMENT_ENDPOINT and "
            "GPT4o_DEPLOYMENT_NAME, plus GPT4o_API_KEY in key mode or GPT4o_AUTH_MODE=entra "
            "with an authorized Azure CLI sign-in. AZURE_OPENAI_* aliases are supported. "
            "Transcription does not require Azure OpenAI."
        )
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith((".openai.azure.com", ".cognitiveservices.azure.com"))
        or parsed.username or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path or parsed.query or parsed.fragment
    ):
        raise ValueError("Use your existing HTTPS Azure OpenAI resource root, without an API path or query.")
    if os.getenv("AZURE_OPENAI_AD_TOKEN"):
        raise ValueError(
            "Remove AZURE_OPENAI_AD_TOKEN: AVIA uses the explicitly selected key or a "
            "renewable Azure CLI token provider, not a static token from the environment."
        )
    return AnalysisConnection(
        endpoint=endpoint,
        deployment=deployment,
        auth_mode=mode,
        key=key if mode == "key" else "",
        api_version=_setting("GPT4o_API_VERSION", "AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )


def _analysis_http_error(exc: APIStatusError, connection: AnalysisConnection) -> AnalysisError:
    code = safe_error_text(exc.code or "Unknown", connection.key, limit=100)
    hints = {
        400: "Check the input size, image format, deployment capabilities, and content policy.",
        401: "Check the configured authentication mode and access to this original OpenAI resource.",
        403: "Check OpenAI data-plane access and the resource's networking policy.",
        404: "Check the existing OpenAI endpoint, deployment name, and API version.",
        429: "The resource is rate-limiting requests. Wait before explicitly trying again.",
    }
    hint = hints.get(exc.status_code, "The OpenAI service could not complete this request.")
    if code.lower() == "authenticationtypedisabled":
        hint = (
            "This resource disables API keys. Set GPT4o_AUTH_MODE=entra (or "
            "AZURE_OPENAI_AUTH_MODE=entra) and use an authorized az login. "
            "Keep the existing endpoint/deployment; no policy change is needed."
        )
    request_id = safe_error_text(exc.request_id or "not returned", connection.key, limit=100)
    retry_after = safe_error_text(exc.response.headers.get("retry-after", ""), connection.key, limit=80)
    suffix = f" Retry-After: {retry_after}." if retry_after else ""
    return AnalysisError(
        f"Azure OpenAI HTTP {exc.status_code} ({code}). {hint} "
        f"Request ID: {request_id}.{suffix} No automatic retry or authentication fallback was made."
    )


def call_openAI(text):
    connection = get_analysis_connection()
    credential = None
    auth = {"api_key": connection.key}
    if connection.auth_mode == "entra":
        credential = AzureCliCredential(process_timeout=30)
        auth = {
            # An explicit empty key prevents the OpenAI SDK from reading an old key alias.
            "api_key": "",
            "azure_ad_token_provider": get_bearer_token_provider(credential, TOKEN_SCOPE),
        }
    try:
        with AzureOpenAI(
            azure_endpoint=connection.endpoint,
            api_version=connection.api_version,
            timeout=ANALYSIS_TIMEOUT,
            max_retries=0,
            **auth,
        ) as client:
            response = client.chat.completions.create(
                model=connection.deployment,
                messages=text,
                temperature=0.0,
            )
    except ClientAuthenticationError as exc:
        raise AnalysisError(
            "Azure OpenAI Entra sign-in failed. Install Azure CLI and run az login with "
            "the identity authorized for the existing OpenAI resource. No key fallback was made."
        ) from exc
    except APITimeoutError as exc:
        raise AnalysisError(
            "Azure OpenAI timed out. The request may have been processed and billed. "
            "No automatic retry was made."
        ) from exc
    except APIConnectionError as exc:
        raise AnalysisError(
            "Could not connect to the configured Azure OpenAI endpoint. Check its network "
            "access and your connection. No automatic retry was made."
        ) from exc
    except APIStatusError as exc:
        raise _analysis_http_error(exc, connection) from exc
    finally:
        if credential is not None:
            credential.close()
    if not response.choices:
        raise AnalysisError("Azure OpenAI returned no analysis choices.")
    choice = response.choices[0]
    if choice.finish_reason in ("length", "content_filter"):
        raise AnalysisError(
            f"Azure OpenAI did not complete the analysis ({choice.finish_reason}). "
            "Review the input size or content policy before trying again."
        )
    content = choice.message.content
    if not isinstance(content, str) or not content.strip():
        raise AnalysisError("Azure OpenAI returned no summary or analysis text.")
    return content


def image_mime_type(data: bytes) -> str:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Upload a non-empty image no larger than 20 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                mime = IMAGE_MIME_TYPES.get(image.format)
                if mime is None:
                    raise ValueError("Use a PNG, JPEG, WebP, or non-animated GIF image.")
                if getattr(image, "is_animated", False):
                    raise ValueError("Animated images are not supported. Upload a single still frame.")
                image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("The uploaded bytes are not a readable PNG, JPEG, WebP, or GIF image.") from exc
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("The image dimensions are too large to process safely. Resize it first.") from exc
    return mime


def encode_image(image):
    return base64.b64encode(image).decode("utf-8")


def analysis_image(image, user_prompt: str | None = None, detected_language="en-US"):
    data = image.getvalue()
    mime_type = image_mime_type(data)
    encoded_image = encode_image(data)
    default_prompt = "Provide a clear, structured analysis of the image: key objects, relationships, actions, context, and any notable details relevant for documentation or presentation."
    question = user_prompt.strip() if user_prompt and user_prompt.strip() else default_prompt
    messages=[
        {"role": "system", "content": "You are a helpful assistant that analyzes images and visual content. Respond succinctly and clearly in English unless otherwise instructed."},
        {"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}}
        ]}
    ]
    return call_openAI(messages)

def analysis_text(userPrompt, text, detected_language="en-US"):
    # Define language-specific prompts
    language_prompts = {
        "en-US": "Please provide a comprehensive content summary focusing on key information and important points. Use clear English formatting.",
        "zh-CN": "请提供一份侧重于关键内容和重要信息的总结。使用良好的中文格式输出",
        "es-ES": "Por favor, proporciona un resumen completo del contenido enfocándose en la información clave y puntos importantes. Usa un formato claro en español.",
        "fr-FR": "Veuillez fournir un résumé complet du contenu en vous concentrant sur les informations clés et les points importants. Utilisez un format français clair.",
        "de-DE": "Bitte erstellen Sie eine umfassende Inhaltszusammenfassung mit Fokus auf wichtige Informationen und Kernpunkte. Verwenden Sie eine klare deutsche Formatierung.",
        "ja-JP": "重要な内容と要点に焦点を当てた包括的なコンテンツ要約を提供してください。明確な日本語の形式を使用してください。",
        "ko-KR": "주요 내용과 중요한 포인트에 중점을 둔 포괄적인 콘텐츠 요약을 제공해 주세요. 명확한 한국어 형식을 사용하세요."
    }
    
    language = (detected_language or "").lower().split("-")[0]
    base_prompt = next(
        (prompt for locale, prompt in language_prompts.items() if locale.lower().split("-")[0] == language),
        "Provide a comprehensive summary of the key information in the same language as the input transcript.",
    )
    
    # If user provided a custom prompt, use it; otherwise use the language-specific default
    final_prompt = userPrompt if userPrompt and userPrompt.strip() else base_prompt
    
    messages=[
        {"role": "system", "content": "You are a helpful assistant that responds in the same language as the input text. Help me with content analysis and summarization!"},
        {"role": "user", "content": [
            {"type": "text", "text": final_prompt},
            {"type": "text", "text": text}
        ]}
    ]
    return call_openAI(messages)