import io
from unittest.mock import Mock
import wave

from speech_fast_transcription import SpeechConnection, TranscriptionResult

TEST_CONNECTION = SpeechConnection(
    endpoint="https://unit-test.cognitiveservices.azure.com",
    key="unit-test-secret",
    region="eastus",
)


def wav_audio(seconds=4):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * (8000 * seconds))
    return buffer.getvalue()


def payload(text="Hello world."):
    return {
        "durationMilliseconds": 10000,
        "combinedPhrases": [{"text": text}],
        "phrases": [{"text": text, "speaker": 0, "locale": "en-US", "confidence": 0}],
    }


def response(body=None, status=200):
    result = Mock()
    result.status_code = status
    result.headers = {}
    result.json.return_value = payload() if body is None else body
    return result


def transcription(engine, seconds=2, text="Hello world."):
    return TranscriptionResult(
        engine=engine,
        text=text,
        display_text=f"Speaker 0: {text}" if text else "",
        locales=["en-US"],
        request_seconds=seconds,
        audio_seconds=10,
        duration_source="service durationMilliseconds",
        started_at_utc="2026-09-08T08:00:00+00:00",
        definition={},
        connection=TEST_CONNECTION.metadata(),
        raw_response=payload(text),
    )


class UploadedAudio(io.BytesIO):
    def __init__(self, name="sample.wav"):
        super().__init__(wav_audio())
        self.name = name
