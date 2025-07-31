import datetime
import json
import logging
import requests
import os
import time
from dotenv import load_dotenv


# Support multiple languages with auto-detection
LOCALES = ["en-US", "zh-CN", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR"]

load_dotenv()
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")


time_line = time.strftime('%Y%m%d%H%M', time.localtime(time.time()))
logger = logging.getLogger()

def print_message(message):
     print('[{}]{}'.format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))
     logger.info(message)

def fast_transcript(audio):
    print_message("Get fast transcription start.")
    print_message("Speech region: " + SPEECH_REGION)
    
    # Use the Fast Transcription API with the latest stable version
    url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2024-11-15"
    print_message("Url: " + url)

    # Fast Transcription API parameters with full multi-language support
    parameters = {
        "locales": LOCALES,  # Support all 7 languages with auto-detection
        "wordLevelTimestampsEnabled": True,
        "profanityFilterMode": "Masked",
        "channels": [0],  # Start with mono channel (most common)
        "diarizationSettings": {
            "enabled": True,
            "minSpeakers": 1,
            "maxSpeakers": 10  # Support up to 10 speakers
        }
    }
    
    result, detected_language = try_transcription(audio, url, parameters)
    
    # Fallback: try without speaker diarization if needed
    if result is None:
        print_message("Retrying without speaker diarization...")
        parameters["diarizationSettings"]["enabled"] = False
        result, detected_language = try_transcription(audio, url, parameters)
    
    # Final fallback: try stereo channels
    if result is None:
        print_message("Retrying with stereo channels...")
        parameters["channels"] = [0, 1]
        parameters["diarizationSettings"]["enabled"] = True
        result, detected_language = try_transcription(audio, url, parameters)
    
    print_message("Get fast transcription end.")
    return result, detected_language

def try_transcription(audio, url, parameters):
    """Helper function to try Fast Transcription API with given parameters"""
    print_message("Parameters: " + json.dumps(parameters))
    
    try:
        # Fast Transcription API uses multipart form data
        files = {
            'definition': (None, json.dumps(parameters), 'application/json'),
            'audio': ('audio.wav', audio.getvalue(), 'audio/wav')
        }
        
        headers = {
            'Ocp-Apim-Subscription-Key': SPEECH_KEY
        }
        
        response = requests.post(url, files=files, headers=headers)
        print_message(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            json_response = response.json()
            
            # Parse the Fast Transcription API response
            phrases = json_response.get('phrases', [])
            sb = []
            detected_language = None
            
            if phrases:
                # Extract detected language from first phrase
                detected_language = phrases[0].get('locale', 'en-US')
                print_message(f"Detected language: {detected_language}")
                
                for phrase in phrases:
                    text = phrase.get('text', '')
                    speaker = phrase.get('speaker', 'Speaker')
                    
                    if text:  # Only add non-empty text
                        if speaker and speaker != 'Speaker':
                            print_message(f"{speaker}: {text}")
                            sb.append(f"{speaker}: {text}")
                        else:
                            sb.append(text)
                
                if sb:
                    result = '\n'.join(sb)
                    print_message("Transcription successful!")
                    return result, detected_language
                else:
                    print_message("No text content found in phrases")
                    return None, None
            else:
                print_message("No phrases found in response")
                return None, None
                
        else:
            print_message(f"Transcription failed with status {response.status_code}: {response.text}")
            return None, None
            
    except Exception as e:
        print_message(f"Transcription error: {str(e)}")
        return None, None
