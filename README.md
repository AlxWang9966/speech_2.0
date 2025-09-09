# AVIA – Audio · Visual · Intelligence Assistant

AVIA is a lightweight, modular Streamlit app that turns raw audio (live or file) and images into structured insight. It combines Azure Speech (SDK + Fast Transcription REST), Azure Translator, and Azure OpenAI (GPT‑4o text + vision) with a small scenario plug‑in pattern.

## Core Features

| Area | What You Get |
|------|--------------|
| Live Mic | Real‑time partial + final captions (UI + instant terminal), optional post‑stop full translation, optional TrueText cleanup |
| Audio File Upload | Auto language detection (7 locales), resilient fast transcription (diarization fallbacks), custom summary prompt, downloadable results |
| Image Analysis | GPT‑4o vision description + optional custom prompt instructions |
| Multi‑Language | en-US, zh-CN, es-ES, fr-FR, de-DE, ja-JP, ko-KR (detection for uploads) |
| Exports | Download transcription, summary, and image analysis outputs as text |
| Architecture | Scenario registry, queue-based UI updates, direct stdout streaming for <100ms terminal captions |

## Architecture Snapshot
```
meeting_summary/
  meeting_sum.py            # App shell + scenario registry UI
  scenarios/
    live_mic.py             # Live mic streaming + optional translation
    audio_file_summary.py   # File upload transcription + summary
    image_analysis.py       # Image + optional custom prompt vision analysis
  llm_analysis.py           # Text + vision analysis helpers (Azure OpenAI)
  speech_fast_transcription.py  # Fast REST transcription w/ fallbacks
speech_to_text/ (legacy)    # Older prototypes (not required for new flows)
```

Live mic latency path: Azure Speech callbacks → (a) direct terminal print (no Streamlit context) + (b) queue → UI drain → throttled rerun (80ms min). Translation computed once after Stop for stability.

## Install & Run

Prereqs: Python 3.9+, Azure resources (Speech, OpenAI, optional Translator).

```bash
git clone https://github.com/AlxWang9966/speech_2.0.git
cd speech_2.0/meeting_summary
pip install -r requirements.txt  # If present
# or minimal:
pip install streamlit azure-cognitiveservices-speech azure-ai-translation openai requests python-dotenv
```

Create `.env` (inside `meeting_summary/`):
```env
SPEECH_KEY=your_speech_key
SPEECH_REGION=your_region
AZURE_OPENAI_API_KEY=your_openai_key
AZURE_OPENAI_ENDPOINT=https://your-openai-endpoint.azure.com/
TRANSLATOR_KEY=optional_translator_key
TRANSLATOR_REGION=your_region
TRANSLATOR_ENDPOINT=https://api.cognitive.microsofttranslator.com/
```

Run:
```bash
streamlit run meeting_sum.py
```
Open http://localhost:8501

## Using the Scenarios

1. Live Microphone
   - Open “Live Mic” card → press Start → speak.
   - Terminal shows instantaneous partial captions; UI shows merged partial + finalized segments.
   - (Optional) Enable Translation, pick target language; final translation appears after Stop.
   - Clear resets transcript; TrueText toggle (Advanced) for cleaner punctuation.

2. Upload Audio: Transcription + Summary
   - Upload wav/mp3/m4a → optional custom summary prompt → Process.
   - Auto-detects language, runs fast transcription with diarization fallbacks.
   - Generates LLM summary; download both artifacts.

3. Image Understanding + Prompt
   - Upload image (png/jpg/jpeg/webp/gif) + optional instruction prompt.
   - Vision model returns structured description / analysis; download result.

## Key Implementation Details

- Queue-driven UI: Background SDK events push tuples to a thread-safe queue; main script drains and triggers selective reruns.
- Direct stdout streaming: Speech recognizing/recognized callbacks write partial and final lines directly (no Streamlit state mutation inside threads).
- Fast Transcription resilience: Progressive fallbacks (full features → no diarization → stereo) for higher success rates.
- One-shot translation: Entire transcript translated once to avoid flicker & cost.

## Add Your Own Scenario
Create `meeting_summary/scenarios/new_feature.py`:
```python
from . import register_scenario
import streamlit as st

@register_scenario(key="my_demo", title="My Demo", description="Short desc.", keywords="Tag")
def run():
    st.write("Hello scenario")
```
It auto-appears on the home grid.

## Roadmap (Short)
- Display diarization speakers in UI
- Clipboard copy & richer export formats (PDF/JSON)
- REST API surface for automation
- Additional analytics (keywords / sentiment)

## Troubleshooting
| Issue | Fix |
|-------|-----|
| No mic text | Check SPEECH_KEY/REGION; microphone permission; terminal errors. |
| Translation blank | Ensure TRANSLATOR_KEY + REGION + ENDPOINT; occurs only after Stop. |
| Partial lag | Lower `PARTIAL_RERUN_INTERVAL` in `live_mic.py` (risk higher CPU). |
| Fast transcription fails | See terminal fallbacks log; verify API version & region. |

---

AVIA focuses on a clean, minimal core: fast capture, accurate transcription, and concise intelligent summaries with minimal moving parts.
