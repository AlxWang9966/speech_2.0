"""Azure Fast and MAI-Transcribe-2 through the Speech transcription REST API."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Optional
from urllib.parse import urlsplit
import wave

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential
from dotenv import load_dotenv
import httpx

load_dotenv(Path(__file__).resolve().parent / ".env")
logger = logging.getLogger(__name__)

API_VERSION = "2025-10-15"
AZURE_FAST = "azure-fast"
MAI_TRANSCRIBE = "mai-transcribe-2"
ENGINE_LABELS = {
    AZURE_FAST: "Azure Speech - Fast",
    MAI_TRANSCRIBE: "MAI-Transcribe-2 (preview)",
}
MAX_AUDIO_BYTES = 300_000_000
# A connection timeout must not also limit writing a large multipart upload.
REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, write=300.0, read=300.0, pool=10.0)
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
SPEECH_LANGUAGES = {
    "en-US": "English (US)",
    "zh-CN": "Chinese (Simplified)",
    "es-ES": "Spanish (Spain)",
    "fr-FR": "French (France)",
    "de-DE": "German",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
}
LOCALES = list(SPEECH_LANGUAGES)
MAI_LANGUAGES = {
    "af": "Afrikaans", "ar": "Arabic", "as": "Assamese", "az": "Azerbaijani",
    "bg": "Bulgarian", "bn": "Bengali", "bs": "Bosnian", "ca": "Catalan",
    "cs": "Czech", "da": "Danish", "de": "German", "el": "Greek",
    "en": "English", "es": "Spanish", "et": "Estonian", "fa": "Persian",
    "fi": "Finnish", "fil": "Filipino", "fr": "French", "gl": "Galician",
    "gu": "Gujarati", "he": "Hebrew", "hi": "Hindi", "hu": "Hungarian",
    "hy": "Armenian", "id": "Indonesian", "is": "Icelandic", "it": "Italian",
    "ja": "Japanese", "kk": "Kazakh", "kn": "Kannada", "ko": "Korean",
    "lt": "Lithuanian", "lv": "Latvian", "mk": "Macedonian", "ml": "Malayalam",
    "mr": "Marathi", "ms": "Malay", "nb": "Norwegian Bokmal", "ne": "Nepali",
    "nl": "Dutch", "or": "Odia", "pa": "Punjabi", "pl": "Polish",
    "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak",
    "sl": "Slovenian", "sv": "Swedish", "sw": "Swahili", "ta": "Tamil",
    "te": "Telugu", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian",
    "ur": "Urdu", "vi": "Vietnamese", "yue": "Cantonese", "zh": "Chinese (Simplified)",
}
MIME_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
}


class TranscriptionError(RuntimeError):
    def __init__(self, message, *, status_code=None, request_seconds=None, diagnostics=None):
        super().__init__(message)
        self.status_code = status_code
        self.request_seconds = request_seconds
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class SpeechConnection:
    endpoint: str
    key: Optional[str] = field(default=None, repr=False)
    region: Optional[str] = None
    auth_mode: str = "key"

    def metadata(self):
        return {
            "endpoint": self.endpoint,
            "region": self.region,
            "api_version": API_VERSION,
            "auth_mode": self.auth_mode,
        }


@dataclass(frozen=True)
class TranscriptionOptions:
    locale: Optional[str] = None
    diarization: bool = True
    profanity_filter: str = "Masked"
    mai_style: str = "verbatim"
    mai_timestamps: str = "word"


@dataclass(frozen=True)
class TranscriptionResult:
    engine: str
    text: str
    display_text: str
    locales: list[str]
    request_seconds: float
    audio_seconds: Optional[float]
    duration_source: str
    started_at_utc: str
    definition: dict[str, Any]
    connection: dict[str, Any]
    raw_response: dict[str, Any]

    @property
    def real_time_factor(self):
        return self.request_seconds / self.audio_seconds if self.audio_seconds else None

    @property
    def audio_speed(self):
        if self.audio_seconds and self.request_seconds > 0:
            return self.audio_seconds / self.request_seconds
        return None


def get_connection(engine: str) -> SpeechConnection:
    if engine not in ENGINE_LABELS:
        raise ValueError(f"Unknown transcription engine: {engine}")
    prefix = "SPEECH"
    if engine == MAI_TRANSCRIBE and any(
        os.getenv(name, "").strip()
        for name in ("MAI_SPEECH_KEY", "MAI_SPEECH_ENDPOINT", "MAI_SPEECH_REGION", "MAI_SPEECH_AUTH_MODE")
    ):
        # Never mix a separate resource's endpoint with the original resource's key.
        prefix = "MAI_SPEECH"
    auth_mode = os.getenv(f"{prefix}_AUTH_MODE", "key").strip().lower()
    if auth_mode not in ("key", "entra"):
        raise ValueError(f"{prefix}_AUTH_MODE must be key or entra.")
    key = os.getenv(f"{prefix}_KEY", "").strip()
    endpoint = os.getenv(f"{prefix}_ENDPOINT", "").strip().rstrip("/")
    region = os.getenv(f"{prefix}_REGION", "").strip().lower() or None
    if auth_mode == "key" and not key:
        raise ValueError(f"Set {prefix}_KEY in meeting_summary/.env.")
    if auth_mode == "entra" and not endpoint:
        raise ValueError(
            f"Entra authentication requires {prefix}_ENDPOINT with the Speech resource's "
            "custom subdomain; a region alone cannot identify the resource."
        )
    if not endpoint:
        if not region or not re.fullmatch(r"[a-z0-9]+", region):
            raise ValueError(f"Set {prefix}_ENDPOINT or a valid {prefix}_REGION in .env.")
        endpoint = f"https://{region}.api.cognitive.microsoft.com"
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(
            (".cognitiveservices.azure.com", ".api.cognitive.microsoft.com")
        )
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{prefix}_ENDPOINT must be an HTTPS Azure Speech resource root, such as "
            "https://<resource>.cognitiveservices.azure.com, without an API path or query. "
            "Do not use an OpenAI endpoint or a Foundry project URL."
        )
    if auth_mode == "entra" and not parsed.hostname.endswith(".cognitiveservices.azure.com"):
        raise ValueError(
            f"Entra authentication requires a custom {prefix}_ENDPOINT such as "
            "https://<resource>.cognitiveservices.azure.com, not a regional endpoint."
        )
    return SpeechConnection(
        endpoint=endpoint,
        key=key if auth_mode == "key" else None,
        region=region,
        auth_mode=auth_mode,
    )


def _authentication_headers(connection: SpeechConnection) -> dict[str, str]:
    if connection.auth_mode == "key":
        if not connection.key:
            raise ValueError("Key authentication requires a Speech resource key.")
        return {"Ocp-Apim-Subscription-Key": connection.key}
    if connection.auth_mode != "entra":
        raise ValueError("Authentication mode must be key or entra.")
    try:
        token = AzureCliCredential(process_timeout=30).get_token(TOKEN_SCOPE).token
    except ClientAuthenticationError as exc:
        raise TranscriptionError(
            "Microsoft Entra sign-in is unavailable. Install Azure CLI and run az login "
            "with the account authorized for this Speech resource, then select the correct "
            "subscription. No transcription request was sent. AVIA will not fall back to a key."
        ) from exc
    return {"Authorization": f"Bearer {token}"}


def build_definition(engine: str, options: TranscriptionOptions) -> dict[str, Any]:
    if engine not in ENGINE_LABELS:
        raise ValueError(f"Unknown transcription engine: {engine}")
    if options.profanity_filter not in ("None", "Masked", "Removed", "Tags"):
        raise ValueError("Invalid profanity filtering mode.")
    definition: dict[str, Any] = {
        "diarization": {"enabled": options.diarization},
        "profanityFilterMode": options.profanity_filter,
    }
    if engine == MAI_TRANSCRIBE:
        if options.mai_style not in ("verbatim", "clean"):
            raise ValueError("MAI transcript style must be verbatim or clean.")
        if options.mai_timestamps not in ("word", "segment", "none"):
            raise ValueError("MAI timestamps must be word, segment, or none.")
        definition["enhancedMode"] = {
            "enabled": True,
            "model": "MAI-Transcribe-2",
            "modelOptions": {
                "transcribeStyle": options.mai_style,
                "timestamps": options.mai_timestamps,
            },
        }
        if options.locale:
            locale = options.locale.lower().split("-")[0]
            if locale not in MAI_LANGUAGES:
                raise ValueError(f"Unsupported MAI language: {options.locale}")
            definition["locales"] = [locale]
    else:
        if options.locale and options.locale not in SPEECH_LANGUAGES:
            raise ValueError(f"Unsupported Azure Fast locale in AVIA: {options.locale}")
        definition["locales"] = [options.locale] if options.locale else LOCALES.copy()
    # Omit channels: the API merges stereo rather than discarding one channel.
    return definition


def validate_audio(audio: bytes, filename: str, engine: str) -> None:
    if engine not in ENGINE_LABELS:
        raise ValueError(f"Unknown transcription engine: {engine}")
    if not audio:
        raise ValueError("The audio file is empty.")
    if len(audio) >= MAX_AUDIO_BYTES:
        raise ValueError("AVIA accepts audio files smaller than 300 MB.")
    extension = Path(filename).suffix.lower()
    allowed = (".wav", ".mp3", ".flac") if engine == MAI_TRANSCRIBE else tuple(MIME_TYPES)
    if extension not in allowed:
        raise ValueError(
            f"{ENGINE_LABELS[engine]} accepts {', '.join(allowed)} in AVIA. "
            "Convert the audio file; changing its extension does not convert its format."
        )


def _wav_duration(audio: bytes, filename: str) -> Optional[float]:
    if Path(filename).suffix.lower() != ".wav":
        return None
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
    except (wave.Error, EOFError) as exc:
        # Non-PCM WAV codecs can still be decoded by Azure.
        logger.info("Local WAV duration unavailable; using service duration instead: %s", exc)
        return None
    if duration >= 5 * 60 * 60:
        raise ValueError("Audio must be shorter than five hours.")
    return duration if duration > 0 else None


def _phrase_list(payload: dict[str, Any], name: str) -> list[dict[str, Any]]:
    phrases = payload.get(name, [])
    if not isinstance(phrases, list) or any(
        not isinstance(phrase, dict) or not isinstance(phrase.get("text", ""), str)
        for phrase in phrases
    ):
        raise ValueError(f"The service returned invalid {name} data.")
    return phrases


def parse_transcription(payload: dict[str, Any]):
    if not isinstance(payload, dict) or not {"phrases", "combinedPhrases"}.intersection(payload):
        raise ValueError("The service returned an unrecognized transcription response.")
    phrases = _phrase_list(payload, "phrases")
    combined = _phrase_list(payload, "combinedPhrases")
    text = "\n".join(p["text"].strip() for p in combined if p.get("text", "").strip())
    if not text:
        text = " ".join(p["text"].strip() for p in phrases if p.get("text", "").strip())
    locales = list(dict.fromkeys(
        p["locale"] for p in phrases if isinstance(p.get("locale"), str) and p["locale"]
    ))
    lines = []
    for phrase in phrases:
        phrase_text = phrase.get("text", "").strip()
        if not phrase_text:
            continue
        speaker = phrase.get("speaker")
        if speaker is not None:
            label = str(speaker)
            if not label.lower().startswith("speaker"):
                label = f"Speaker {label}"
            phrase_text = f"{label}: {phrase_text}"
        lines.append(phrase_text)
    display_text = "\n".join(lines) if lines else text
    milliseconds = payload.get("durationMilliseconds")
    if milliseconds is not None and (
        isinstance(milliseconds, bool)
        or not isinstance(milliseconds, (int, float))
        or not math.isfinite(milliseconds)
        or milliseconds < 0
    ):
        raise ValueError("The service returned an invalid audio duration.")
    audio_seconds = milliseconds / 1000 if milliseconds else None
    return text, display_text, locales, audio_seconds


def _redact(value: str, credential: str) -> str:
    return value.replace(credential, "[redacted]") if credential else value


def _response_diagnostics(response, credential: str) -> dict[str, Any]:
    details: dict[str, Any] = {"kind": "http_error", "timeouts_seconds": REQUEST_TIMEOUT.as_dict()}
    for name in ("apim-request-id", "x-ms-request-id", "x-ms-error-code", "retry-after", "server", "content-type"):
        value = response.headers.get(name)
        if isinstance(value, str):
            details[name] = _redact(value, credential)[:300]
    retry_after = details.get("retry-after")
    if retry_after:
        try:
            if retry_after.strip().isdigit():
                deadline = time.time() + float(retry_after)
            else:
                retry_date = parsedate_to_datetime(retry_after)
                if retry_date.tzinfo is None:
                    retry_date = retry_date.replace(tzinfo=timezone.utc)
                deadline = retry_date.timestamp()
            if not math.isfinite(deadline):
                raise ValueError("Non-finite Retry-After")
        except (ValueError, TypeError, OverflowError, OSError):
            details["retry_after_parse_error"] = "The service returned an invalid Retry-After value."
        else:
            details["retry_not_before"] = deadline
    return details


def _http_error(response, credential: str, elapsed: float) -> TranscriptionError:
    hints = {
        400: "Check audio format, language/options, and MAI availability for this resource.",
        401: "Check the authentication mode, Speech endpoint, and identity or key access.",
        403: "Check Speech data-plane role assignments, networking restrictions, and model availability.",
        404: "Check the Speech endpoint and model availability in this resource's region.",
        413: "The service rejected the audio size; use a smaller file.",
        429: "The service is rate-limiting requests. Wait before running again.",
        500: "The Speech service could not complete this attempt. Retry the failed request.",
        502: "The Speech service gateway failed this attempt. Retry the failed request.",
        503: "The Speech service is temporarily unavailable. Retry the failed request after any Retry-After delay.",
        504: "The Speech service gateway timed out. The request may still have been processed; retrying may incur charges.",
    }
    detail = ""
    diagnostics = _response_diagnostics(response, credential)
    try:
        body = response.json()
    except ValueError:
        body = None
        text = response.text
        if isinstance(text, str) and text.startswith("MAI service returned an error:"):
            start = text.find("{")
            if start >= 0:
                try:
                    body = json.loads(text[start:])
                except json.JSONDecodeError:
                    diagnostics["service_error_parse_error"] = "The nested MAI error was not valid JSON."
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            if isinstance(error.get("message"), str):
                detail = " " + _redact(error["message"], credential)[:500]
            if isinstance(error.get("code"), str):
                diagnostics["service_code"] = _redact(error["code"], credential)[:200]
    if not detail and isinstance(response.text, str) and response.text:
        diagnostics["response_excerpt"] = " ".join(_redact(response.text, credential).split())[:600]
    hint = hints.get(response.status_code, "The Speech service request failed; try again later.")
    if diagnostics.get("service_code") == "diarization_unavailable":
        hint = (
            "MAI's speaker-diarization stage failed. For a transcription-only comparison, "
            "turn off 'Identify speakers (diarization)' and start a new run for both engines. "
            "No settings were changed automatically."
        )
    if response.status_code == 403 and "key based authentication is disabled" in detail.lower():
        hint = (
            "This resource disables API keys. Configure SPEECH_AUTH_MODE=entra (or "
            "MAI_SPEECH_AUTH_MODE=entra) and the resource's custom Speech endpoint. "
            "Use an authorized Azure CLI sign-in; no resource security policy needs to change."
        )
    retry_after = diagnostics.get("retry-after")
    if retry_after:
        hint += f" Retry-After: {retry_after}."
    return TranscriptionError(
        f"HTTP {response.status_code}. {hint}{detail}",
        status_code=response.status_code,
        request_seconds=elapsed,
        diagnostics=diagnostics,
    )


def _transport_error(exc: httpx.RequestError, elapsed: float, credential: str) -> TranscriptionError:
    if isinstance(exc, httpx.WriteTimeout):
        kind = "upload_timeout"
        message = "The audio upload stalled. Check the upload connection, then retry the failed request."
    elif isinstance(exc, httpx.ConnectTimeout):
        kind = "connection_timeout"
        message = "Connecting to the Speech endpoint timed out. Check endpoint connectivity."
    elif isinstance(exc, httpx.ReadTimeout):
        kind = "response_timeout"
        message = (
            "Waiting for the Speech response timed out. The service may still have processed "
            "and billed this attempt."
        )
    elif isinstance(exc, httpx.WriteError):
        kind = "upload_error"
        message = "The connection failed while uploading the audio. Retry the failed request."
    else:
        kind = "transport_error"
        message = f"The Speech request failed at the transport layer ({type(exc).__name__})."
    return TranscriptionError(
        f"{message} No automatic retry was made; see request diagnostics for details.",
        request_seconds=elapsed,
        diagnostics={
            "kind": kind,
            "exception_type": type(exc).__name__,
            "detail": _redact(str(exc), credential)[:1000],
            "timeouts_seconds": REQUEST_TIMEOUT.as_dict(),
        },
    )


def transcribe_audio(
    audio: bytes,
    filename: str,
    engine: str = AZURE_FAST,
    options: Optional[TranscriptionOptions] = None,
    connection: Optional[SpeechConnection] = None,
) -> TranscriptionResult:
    """Make exactly one request; never substitute models, retry, or cache results."""
    options = options or TranscriptionOptions()
    validate_audio(audio, filename, engine)
    definition = build_definition(engine, options)
    connection = connection or get_connection(engine)
    local_duration = _wav_duration(audio, filename)
    headers = _authentication_headers(connection)
    url = f"{connection.endpoint}/speechtotext/transcriptions:transcribe?api-version={API_VERSION}"
    files = {
        "definition": (None, json.dumps(definition), "application/json"),
        "audio": (Path(filename).name, audio, MIME_TYPES[Path(filename).suffix.lower()]),
    }
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    credential = next(iter(headers.values())).removeprefix("Bearer ")
    try:
        response = httpx.post(
            url,
            files=files,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=False,
        )
    except httpx.RequestError as exc:
        raise _transport_error(exc, time.perf_counter() - started, credential) from exc
    elapsed = time.perf_counter() - started
    try:
        if response.status_code != 200:
            raise _http_error(response, credential, elapsed)
        try:
            payload = response.json()
            text, display_text, locales, service_duration = parse_transcription(payload)
            if not options.diarization:
                display_text = text
        except ValueError as exc:
            raise TranscriptionError(
                f"Invalid Speech response: {exc}", status_code=200, request_seconds=elapsed,
                diagnostics={**_response_diagnostics(response, credential), "kind": "invalid_response"},
            ) from exc
    finally:
        response.close()
    audio_seconds = local_duration if local_duration is not None else service_duration
    duration_source = (
        "WAV header" if local_duration is not None
        else "service durationMilliseconds" if service_duration is not None
        else "unavailable"
    )
    return TranscriptionResult(
        engine=engine,
        text=text,
        display_text=display_text,
        locales=locales,
        request_seconds=elapsed,
        audio_seconds=audio_seconds,
        duration_source=duration_source,
        started_at_utc=started_at,
        definition=definition,
        connection=connection.metadata(),
        raw_response=payload,
    )


def fast_transcript(audio):
    """Compatibility entry point returning (text, locale), with a diarization fallback."""
    for diarization in (True, False):
        try:
            result = transcribe_audio(
                audio.getvalue(),
                getattr(audio, "name", "audio.wav"),
                options=TranscriptionOptions(diarization=diarization),
            )
        except TranscriptionError as exc:
            logger.error("Azure Fast transcription failed: %s", exc)
            if diarization and exc.status_code == 400:
                logger.info("Retrying the legacy call without diarization.")
                continue
            return None, None
        except ValueError as exc:
            logger.error("Invalid Azure Fast transcription configuration/input: %s", exc)
            return None, None
        return result.display_text, result.locales[0] if result.locales else None
    return None, None
