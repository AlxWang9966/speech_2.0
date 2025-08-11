import datetime
import json
import logging
import requests
import os
import time
from dotenv import load_dotenv

"""speech_fast_transcription.py
Wrapper for Azure Fast Transcription REST API with:
- Multi-locale automatic language detection (7 locales)
- Speaker diarization (retry fallbacks if failure)
- Graceful degradation strategy (disable diarization, add stereo)

Returns (transcription_text, detected_language) or (None, None) on failure.
"""

# Support multiple languages with auto-detection
LOCALES = ["en-US", "zh-CN", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR"]

load_dotenv()
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")

logger = logging.getLogger()

def print_message(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")
    logger.info(message)

def fast_transcript(audio):
    """Primary entry: attempt transcription with resilience fallbacks."""
    print_message("Fast transcription start")
    url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2024-11-15"

    # Base parameters (most capable)
    parameters = {
        "locales": LOCALES,
        "wordLevelTimestampsEnabled": True,
        "profanityFilterMode": "Masked",
        "channels": [0],  # mono baseline
        "diarizationSettings": {"enabled": True, "minSpeakers": 1, "maxSpeakers": 10}
    }

    result, detected_language = try_transcription(audio, url, parameters)

    # Fallback 1: disable diarization
    if result is None:
        print_message("Retry without diarization")
        parameters["diarizationSettings"]["enabled"] = False
        result, detected_language = try_transcription(audio, url, parameters)

    # Fallback 2: enable stereo + re-enable diarization
    if result is None:
        print_message("Retry stereo + diarization")
        parameters["channels"] = [0, 1]
        parameters["diarizationSettings"]["enabled"] = True
        result, detected_language = try_transcription(audio, url, parameters)

    print_message("Fast transcription end")
    return result, detected_language

def try_transcription(audio, url, parameters):
    """Invoke Fast Transcription API once with supplied parameters."""
    print_message("Parameters: " + json.dumps(parameters))
    try:
        files = {
            'definition': (None, json.dumps(parameters), 'application/json'),
            'audio': ('audio.wav', audio.getvalue(), 'audio/wav')
        }
        headers = {'Ocp-Apim-Subscription-Key': SPEECH_KEY}
        response = requests.post(url, files=files, headers=headers)
        print_message(f"HTTP {response.status_code}")

        if response.status_code != 200:
            print_message(f"Failure: {response.text[:200]}")
            return None, None

        json_response = response.json()
        phrases = json_response.get('phrases', [])
        if not phrases:
            print_message("No phrases in response")
            return None, None

        detected_language = phrases[0].get('locale', 'en-US')
        lines = []
        for phrase in phrases:
            text = phrase.get('text', '')
            speaker = phrase.get('speaker')
            if text:
                if speaker and speaker != 'Speaker':
                    lines.append(f"{speaker}: {text}")
                else:
                    lines.append(text)
        if not lines:
            print_message("Empty phrase texts")
            return None, None

        result = '\n'.join(lines)
        print_message("Success")
        return result, detected_language
    except Exception as e:
        print_message(f"Exception: {e}")
        return None, None
