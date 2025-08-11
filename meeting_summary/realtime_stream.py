import os
import time
import wave
import threading
from io import BytesIO
from typing import List, Optional  # Removed unused Tuple

import azure.cognitiveservices.speech as speechsdk
from azure.ai.translation.text import TextTranslationClient
from azure.core.credentials import AzureKeyCredential

"""realtime_stream.py
Utility for simulating a real-time streaming session by pushing an uploaded
WAV file into an Azure Speech PushAudioInputStream. Provides optional per-
segment translation using Azure Translator.

Design:
- Writer thread feeds PCM frames to push stream (optional real-time pacing)
- Speech SDK callbacks update an in-memory state object (StreamingResult)
- Caller invokes continuous_transcribe_and_translate and receives populated
  result object after completion (blocking convenience wrapper)

Note: This module purposefully has no Streamlit references to keep it UI-agnostic.
"""

SPEECH_KEY = os.getenv("SPEECH_KEY", "")
SPEECH_REGION = os.getenv("SPEECH_REGION", "eastus")
TRANSLATOR_KEY = os.getenv("TRANSLATOR_KEY", "")
TRANSLATOR_REGION = os.getenv("TRANSLATOR_REGION", "eastasia")
TRANSLATOR_ENDPOINT = os.getenv("TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com")

class StreamingResult:
    """Holds incremental streaming transcription + translation state."""
    def __init__(self):
        self.partial: str = ""                  # Latest interim hypothesis
        self.final_segments: List[str] = []      # Finalized recognized lines
        self.translated_segments: List[str] = [] # Translated counterparts (if enabled)
        self.detected_language: Optional[str] = None
        self.done = False                        # Session termination flag
        self.error: Optional[str] = None         # Error message if failure occurs

def _push_stream_writer(wav_bytes: BytesIO, stream: speechsdk.audio.PushAudioInputStream, frame_size: int = 4096, sleep_real_time: bool = True):
    """Feed audio frames into push stream; optionally pace to approximate real-time."""
    wav_bytes.seek(0)
    with wave.open(wav_bytes, 'rb') as wf:
        frame_rate = wf.getframerate()
        frame_duration = frame_size / frame_rate if frame_rate else 0.0
        while True:
            data = wf.readframes(frame_size)
            if not data:
                break
            stream.write(data)
            if sleep_real_time:
                time.sleep(frame_duration)
    stream.close()


def continuous_transcribe_and_translate(audio_file, source_language: str, target_language: str, enable_translation: bool = True) -> StreamingResult:
    """Simulate continuous streaming for an uploaded audio file.

    This blocks until all audio is pushed and recognition session completes.
    Returns a populated StreamingResult with segments (and translations if enabled).
    """
    result_state = StreamingResult()

    if not SPEECH_KEY:
        result_state.error = "Missing SPEECH_KEY environment variable"
        result_state.done = True
        return result_state

    # Configure speech recognition
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.set_property(speechsdk.PropertyId.SpeechServiceResponse_RequestWordLevelTimestamps, "True")
    speech_config.set_property(speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption, "TrueText")
    speech_config.set_profanity(speechsdk.ProfanityOption.Raw)
    speech_config.output_format = speechsdk.OutputFormat.Detailed

    push_stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, language=source_language, audio_config=audio_config)

    # Optional translator client
    translator_client = None
    if enable_translation and TRANSLATOR_KEY:
        try:
            translator_client = TextTranslationClient(credential=AzureKeyCredential(TRANSLATOR_KEY), region=TRANSLATOR_REGION, endpoint=TRANSLATOR_ENDPOINT)
        except Exception as e:
            result_state.error = f"Translator init failed: {e}"

    # Callback handlers
    def recognizing_cb(evt: speechsdk.SpeechRecognitionEventArgs):
        if evt.result.reason == speechsdk.ResultReason.RecognizingSpeech:
            result_state.partial = evt.result.text

    def recognized_cb(evt: speechsdk.SpeechRecognitionEventArgs):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text
            if text:
                result_state.final_segments.append(text)
                # Translate segment if enabled & available
                if translator_client and target_language and target_language != source_language:
                    try:
                        tr = translator_client.translate(body=[text], to_language=[target_language], from_language=source_language)
                        translated_text = tr[0]['translations'][0]['text']
                    except Exception:
                        translated_text = "[Translation failed]"
                    result_state.translated_segments.append(translated_text)
                elif translator_client is None and enable_translation:
                    result_state.translated_segments.append("[Translator not configured]")

    def session_stopped_cb(evt):
        result_state.done = True

    recognizer.recognizing.connect(recognizing_cb)
    recognizer.recognized.connect(recognized_cb)
    recognizer.session_stopped.connect(session_stopped_cb)

    # Read uploaded file bytes (assumed WAV) into memory
    wav_bytes = BytesIO(audio_file.read())

    # Writer thread simulates real-time pushing
    writer_thread = threading.Thread(target=_push_stream_writer, args=(wav_bytes, push_stream))
    writer_thread.start()

    recognizer.start_continuous_recognition()

    # Poll until session indicates completion
    while not result_state.done:
        # Heuristic: if audio drained and no active partial, request stop
        if not writer_thread.is_alive() and not result_state.partial:
            time.sleep(0.5)  # Allow final callbacks to fire
            recognizer.stop_continuous_recognition()
            result_state.done = True
            break
        time.sleep(0.2)

    writer_thread.join(timeout=2)
    return result_state
