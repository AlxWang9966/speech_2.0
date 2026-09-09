# AVIA - Audio, Visual, Intelligence Assistant

AVIA is a modular Streamlit app for live captions, audio-file transcription, and image analysis. The **Audio Transcription Lab** integrates **MAI-Transcribe-2 (preview)** alongside Azure Speech Fast Transcription, with repeatable performance measurements and optional Azure OpenAI summaries.

## Workspaces

| Workspace | Capabilities |
| --- | --- |
| Audio Transcription Lab | Azure Fast, MAI-Transcribe-2, or a side-by-side comparison on the same uploaded audio; speaker labels, language controls, timing, optional reference-based WER/CER, and JSON/text exports |
| Live Microphone - Azure Speech SDK | Live English captions from the computer running Streamlit; optional translation after Stop and TrueText cleanup. This does **not** use MAI-Transcribe-2. |
| Image Understanding + Prompt | GPT-4o vision analysis with an optional custom prompt, saved results, stale-input notices, and downloads |

Azure Fast remains the default file-transcription engine. Summarization is now a separate **Generate summary** action, so OpenAI credentials and LLM latency are not required for transcription or its measurements.

## Install and run on Windows

Requires Python **3.10+** (Python 3.12 recommended), Streamlit **1.47+**, and Speech SDK **1.45+**. The requirements file includes these minimum versions. From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\meeting_summary\requirements.txt
if (-not (Test-Path .\meeting_summary\.env)) {
    Copy-Item .\meeting_summary\.env.example .\meeting_summary\.env
}
```

Edit `meeting_summary\.env` with your resource credentials. Do not overwrite an existing `.env` or commit keys.

```env
SPEECH_KEY=your_speech_resource_key
SPEECH_REGION=eastus
# Authentication defaults to key:
# SPEECH_AUTH_MODE=key
# Optional resource-root endpoint, otherwise the regional Speech endpoint is used:
# SPEECH_ENDPOINT=https://your-resource.cognitiveservices.azure.com
```

Start from `meeting_summary` so Streamlit loads the included theme and upload-size configuration:

```powershell
Set-Location .\meeting_summary
..\.venv\Scripts\python.exe -m streamlit run .\meeting_sum.py
```

Open `http://localhost:8501`. The `.env` location is resolved relative to the app, not the shell's current directory.

### MAI-Transcribe-2 connection

MAI is selected through the **Speech transcription REST API**, not an OpenAI audio endpoint or the existing live-microphone SDK:

```text
POST {speech-resource-root}/speechtotext/transcriptions:transcribe?api-version=2025-10-15
```

The multipart `definition` explicitly includes:

```json
{
  "enhancedMode": {
    "enabled": true,
    "model": "MAI-Transcribe-2",
    "modelOptions": {
      "transcribeStyle": "verbatim",
      "timestamps": "word"
    }
  }
}
```

Both engines reuse `SPEECH_KEY` and `SPEECH_ENDPOINT` or `SPEECH_REGION` by default. The resource must support the selected model in its region; a valid Azure Fast key is not proof of MAI access. No separate Azure OpenAI model deployment is used for MAI.

If your existing Speech resource cannot use MAI, configure a **separate, compatible resource** without changing live-microphone credentials:

```env
MAI_SPEECH_KEY=your_other_speech_resource_key
MAI_SPEECH_ENDPOINT=https://your-mai-resource.cognitiveservices.azure.com
# Optional region metadata, or use the region instead of an endpoint:
MAI_SPEECH_REGION=eastus
```

If any `MAI_SPEECH_*` override is set, it must provide a complete configuration: in key mode, its own key **and** endpoint or region; in Entra mode, its authentication mode **and** custom endpoint. AVIA never silently combines one resource's key with another resource's endpoint. Use an HTTPS Azure Speech resource root, not a Foundry project URL or a full transcription API URL. Different resources/regions can have different networking latency and capacity; the exported run records the endpoints and authentication modes.

MAI-Transcribe-2 is in **public preview**, not covered by a production SLA. Consult the current [MAI model documentation](https://learn.microsoft.com/azure/ai-services/speech-service/mai-transcribe?pivots=programming-language-rest) and [region availability](https://learn.microsoft.com/azure/ai-services/speech-service/regions?tabs=llmspeech). AVIA's integration follows the model-specific MAI-Transcribe-2 documentation, including its diarization and style controls, rather than older generic MAI feature tables.

### Microsoft Entra ID / resources with keys disabled

The file-transcription lab and live-microphone SDK both support keyless authentication without changing resource security policy:

```env
SPEECH_AUTH_MODE=entra
SPEECH_ENDPOINT=https://your-resource.cognitiveservices.azure.com
SPEECH_REGION=eastus
```

Sign in with [Azure CLI](https://learn.microsoft.com/cli/azure/authenticate-azure-cli-interactively) on the computer running Streamlit:

```powershell
az login
az account set --subscription "<your-subscription-name-or-id>"
```

AVIA uses `AzureCliCredential` and the `https://cognitiveservices.azure.com/.default` scope, sending only a Bearer token in Entra mode. It does not store/export tokens or fall back to an API key. The existing `SPEECH_KEY` can remain in `.env` but is ignored by the lab in Entra mode. Token acquisition happens before request timing starts.

Entra authentication requires a **custom Speech subdomain**; a regional endpoint is insufficient. The signed-in identity needs **Cognitive Services Speech User** or equivalent Speech data-plane permissions on that resource. Owner/Contributor management access alone is not enough. See [Speech roles and authentication](https://learn.microsoft.com/azure/ai-services/speech-service/role-based-access-control). AVIA does not grant roles, enable key authentication, or change networking settings.

For a separate keyless MAI resource, set `MAI_SPEECH_AUTH_MODE=entra` and `MAI_SPEECH_ENDPOINT=https://<resource>.cognitiveservices.azure.com`. Restart Streamlit after changing existing environment settings. This authentication uses the **server's** Azure CLI identity, not the browser visitor's identity.

Live recognition uses the same `SPEECH_AUTH_MODE` and custom `SPEECH_ENDPOINT`. It passes `AzureCliCredential` to `SpeechConfig(token_credential=..., endpoint=...)`; the native Speech SDK obtains and renews tokens using their expiry time. AVIA does not install a static token or artificially extend its lifetime. See [Speech SDK Entra authentication](https://learn.microsoft.com/azure/ai-services/speech-service/how-to-configure-azure-ad-auth?pivots=programming-language-python).

### Optional OpenAI and Translator configuration

For summaries and image analysis:

```env
GPT4o_AUTH_MODE=key
GPT4o_API_KEY=your_openai_key
GPT4o_DEPLOYMENT_ENDPOINT=https://your-openai-resource.openai.azure.com/
GPT4o_DEPLOYMENT_NAME=your_gpt_4o_deployment
```

The aliases `AZURE_OPENAI_AUTH_MODE`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_DEPLOYMENT` are also accepted; the existing `GPT4o_*` names take precedence. The client is created only when analysis is requested. `GPT4o_API_VERSION` / `AZURE_OPENAI_API_VERSION` can override the default `2024-02-01`.

If the **existing OpenAI resource** returns `AuthenticationTypeDisabled`, set `GPT4o_AUTH_MODE=entra` (or `AZURE_OPENAI_AUTH_MODE=entra`) and retain its original endpoint/deployment. AVIA uses a renewable Azure CLI token provider with the Cognitive Services scope, ignores old keys in this mode, and never switches resources or enables local authentication. The identity needs OpenAI data-plane access such as **Cognitive Services OpenAI User**. Remove any static `AZURE_OPENAI_AD_TOKEN`; it must not override the selected authentication mode. See [keyless Azure OpenAI connections](https://learn.microsoft.com/azure/developer/ai/keyless-connections).

OpenAI calls have explicit connection/pool (10 seconds), upload-write (60 seconds), and response-read (120 seconds) inactivity timeouts and **no automatic retries**. Errors and incomplete/empty output are not shown as successful analyses. Summaries remain separate from transcription timing.

For translation of live captions after Stop:

```env
TRANSLATOR_AUTH_MODE=key
TRANSLATOR_KEY=your_original_translator_key
TRANSLATOR_REGION=your_original_translator_region
TRANSLATOR_ENDPOINT=https://api.cognitive.microsofttranslator.com/
```

If the **original Translator resource** has `disableLocalAuth=true`, old keys cannot authenticate even when the endpoint and region are correct. The global endpoint may return 401; a resource-specific endpoint can identify the policy as HTTP 403 `AuthenticationTypeDisabled`. Fix the client authentication, **not** the resource's region or security policy:

```env
TRANSLATOR_AUTH_MODE=entra
TRANSLATOR_RESOURCE_ID=/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.CognitiveServices/accounts/<original-translator-name>
```

Keep `TRANSLATOR_ENDPOINT`, the original `TRANSLATOR_REGION`, and the original resource ID together. Global-endpoint Entra requests carry the token, `Ocp-Apim-ResourceId`, and `Ocp-Apim-Subscription-Region`; the old key is ignored. A custom `https://<original-translator>.cognitiveservices.azure.com` root is also supported. The identity needs Translator data-plane access such as **Cognitive Services User**. AVIA never borrows `SPEECH_REGION` or silently redirects translation to the Speech resource. See [Translator authentication](https://learn.microsoft.com/azure/ai-services/translator/text-translation/reference/authentication).

Translation maps Speech locales to Translator codes, including `zh-CN` to `zh-Hans` and `en-US` to `en`. Each explicit action submits one request with a 10-second connection timeout, 60-second read timeout, and no automatic retry. The service's 50,000-character single-request limit is enforced before submission. Errors preserve the transcript and are displayed separately from successful translation.

## Live captions and images

**Live microphone:** Start captures English audio from the **computer running Streamlit**, not from a remote browser. Each Start creates a new transcript and an isolated SDK worker/event queue. SDK callbacks never access Streamlit; a 250 ms fragment refresh drains final/interim captions without a forced-rerun loop. TrueText remains optional. Terminal output is opt-in, final-captions-only; AVIA no longer writes automatic transcript log files.

Stop drains final callbacks before translation. Clear and Back stop the worker before discarding captions or navigating. A stop that has not completed within 10 seconds remains visibly pending; the app does not claim the microphone was released or start another capture. Lack of an active workspace heartbeat triggers shutdown after 30 seconds. SDK cancellation details remain visible. Download the transcript before starting a new capture. Optional translation runs once after a successful Stop; manual retries or target changes require **Translate saved transcript**, not a UI refresh.

**Images:** PNG, JPEG, WebP, and non-animated GIF are accepted up to 20 MB. The MIME type is detected from validated image bytes, not guessed from the filename. Animated or unsafe/invalid images are rejected locally. Analysis and downloads survive reruns; changed images/prompts mark saved results as stale. Failed requests do not erase earlier successful results or trigger retries on refresh.

## Transcribe and compare

1. Open **Audio Transcription Lab** and select Azure Fast, MAI-Transcribe-2, or **Compare both**.
2. Upload WAV, MP3, or FLAC. Azure Fast also retains M4A support. AVIA accepts files **smaller than 300 MB**; the real codec must be supported by the service. Renaming an extension does not convert audio. Azure also enforces duration limits.
3. Select the known spoken language or leave automatic detection. Azure Fast preserves AVIA's seven candidate locales: en-US, zh-CN, es-ES, fr-FR, de-DE, ja-JP, ko-KR. MAI automatic mode covers its 60 supported languages and supports code switching. A forced MAI language is a strong constraint; omit it for mixed-language audio.
4. Configure speaker diarization, profanity filtering, and MAI style/timestamp detail. Defaults request diarization and word timestamps, retain masked profanity, and use MAI `verbatim`. Stereo channels are not discarded or requested separately.
5. Optionally paste a known reference transcript, without speaker labels or timestamps. Select one to five requests per engine, then run. Each request may incur Azure charges.
6. Compare the per-engine medians and individual results. Transcripts appear side by side; download the complete benchmark JSON or individual text outputs. Generate a summary separately if needed.

The lab never retries automatically, silently changes settings, substitutes models, or caches transcription responses. A failure for one engine remains visible and does not erase successful results from the other. Results survive UI reruns and downloads; changing inputs clearly marks the saved results as belonging to the earlier run.

Use **Retry failed requests** to retry only unresolved entries with their original audio, options, and endpoint. Earlier failures remain in the table/JSON with numbered attempts; successful transcripts and summaries are retained. Each retry can incur charges. The app honors a service-provided `Retry-After` before allowing a retry. If you change the audio, settings, or connection, start a new run instead.

Large files are transferred twice: first from the browser to Streamlit, then from Streamlit to Azure for each request. The HTTPX transport has independent connection (10 seconds), upload-write (300 seconds), and response-read (300 seconds) inactivity timeouts. A slow upload no longer shares the shorter connection timeout. These are inactivity limits, not a total-job time limit.

**Request diagnostics** preserves the transport error category, safe service request IDs, timeout settings, response error/excerpt, and `Retry-After` when available. Credentials are redacted. In particular, a MAI `diarization_unavailable` error identifies a failure in the provider's speaker-labeling stage, not necessarily in transcription. For a transcription-only comparison, explicitly turn off **Identify speakers (diarization)** and start a new run for both engines; AVIA never silently disables it.

This provider limitation can appear as HTTP 503 with a nested `diarization_unavailable` / HTTP 400 error on a large recording. Successful transcription-only requests do **not** mean speaker diarization is healthy. Disabling it is an explicit user choice and must apply to both engines in a matched comparison.

## What the measurements mean

| Measurement | Definition and caveats |
| --- | --- |
| Request time | Client wall-clock time around one HTTP request, including upload, service processing, and download. Excludes Entra token acquisition, local scoring, rendering, and summarization. **Not model-only inference time.** |
| Audio duration | WAV header when readable; otherwise the service's top-level `durationMilliseconds`. Not the last speech segment or sum of speech-only segments. Missing duration means no RTF/speed value. |
| Real-time factor (RTF) | Request seconds / audio seconds. Lower is better; below 1 means the request finished faster than the audio's duration. |
| Audio speed | Audio seconds / request seconds. For example, 10x means ten seconds of audio processed per second of request time. Not a model-to-model speedup. |
| WER / CER | Levenshtein word/character edits divided by reference length. Lower is better. Only calculated when a nonempty reference is supplied; not derived from model confidence. Rates can exceed 100%. |

Scoring normalizes Unicode with NFKC, case-folds, removes Unicode punctuation, and collapses whitespace. WER uses whitespace-delimited words. CER excludes whitespace and counts Unicode code points; prefer it for Chinese, Japanese, and other languages without word spaces. Numbers and spelling variants are not normalized. Speaker labels are excluded; diarization quality is not evaluated. A punctuation-only reference is rejected. An empty hypothesis with a real reference scores as deletions, not perfect accuracy.

Comparisons send **identical audio bytes** sequentially and alternate engine order across repetitions. All successful requests, including the first, contribute to medians; failed attempts are counted separately and retain errors and any HTTP elapsed time. Authentication failures before submission have no HTTP request time. Use known-language settings, matched features, several recordings, and repeated trials for meaningful comparisons. MAI `clean` style and profanity filtering intentionally change words, affecting reference error rates.

Manual retries are additional numbered attempts, not new configured repetitions. Successful-request medians exclude failed-request time and the wait before retrying; they do not measure total recovery time. JSON schema version 2 records attempt numbers and failure diagnostics.

The JSON export includes the audio SHA-256, original filename, UTC run time, options, endpoints, reference, transcripts, raw responses, and measurements. It includes **no API keys or uploaded audio bytes**, but its text can still contain sensitive information. No price estimate or universal "fastest/most accurate" ranking is inferred from a local run.

## Architecture

```text
meeting_summary/
  meeting_sum.py                 # Native, theme-aware Streamlit shell
  speech_fast_transcription.py    # Shared Speech REST adapter; explicit MAI model selection
  speech_streaming.py             # Isolated continuous SDK worker, credential renewal, cleanup
  transcription_benchmark.py      # Repeat scheduling, timing reports, WER/CER
  llm_analysis.py                 # Lazy Azure OpenAI text and vision calls
  translation.py                  # Original-resource Translator key/Entra configuration
  service_errors.py               # Bounded, credential-redacted diagnostics
  scenarios/
    audio_file_summary.py        # Audio Transcription Lab and optional summary
    live_mic.py                  # Periodic caption fragment and explicit post-stop translation
    image_analysis.py            # Vision workflow
  tests/                         # unittest and Streamlit AppTest coverage; no live API calls
  requirements.txt
  .env.example
```

The legacy `fast_transcript(audio)` tuple entry point remains available for plug-ins. It logs errors and can retry an Azure HTTP 400 once without diarization. The benchmark uses `transcribe_audio(...)` instead, which always makes exactly one request. The standalone `realtime_stream.py` prototype is not registered in the modular app; use the live workspace for the supported lifecycle/authentication path.

To add a scenario, decorate its render function with `register_scenario(...)` and add its module to `_DEF_MODULES` in `meeting_sum.py`.

## Tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s .\meeting_summary\tests -t .\meeting_summary -v
```

These tests mock cloud requests and microphone access. They cover the REST contract, key/Entra configuration, image MIME/validation, scoring, benchmark scheduling, cancellation and shutdown, stale callback isolation, post-stop translation, and persisted UI results/errors. Live readiness must be checked separately with your authorized resources. Use prerecorded synthetic WAV input through `LiveSpeechSession(audio_config=speechsdk.audio.AudioConfig(filename=...))` to exercise the real continuous path without opening a physical microphone. Automated readiness does not verify physical microphone permissions or hardware.

## Privacy and local credentials

`.env`, virtual environments, bytecode, Streamlit secrets, and local transcript logs are ignored. Never commit real resource IDs, endpoints, keys, tokens, recordings, transcripts, or benchmark/probe exports. Example settings and tests use placeholders. Downloaded reports include transcript/reference text and endpoint metadata and should be treated as private.

OpenAI outputs are not printed to the server log. Live terminal captions are off by default; enabling them may leave text in terminal history. Azure calls use the identity/configuration on the Streamlit server, not each browser visitor's identity. This local demo does not add user authentication; do not expose it publicly without your own access controls.

## Troubleshooting

| Problem | Action |
| --- | --- |
| MAI returns HTTP 400/404 | Confirm this resource supports MAI-Transcribe-2 in its region. Check the current model documentation and selected options. The app does not fall back to another model. |
| HTTP 403: key-based authentication disabled | Use `SPEECH_AUTH_MODE=entra` with the custom Speech endpoint and an authorized Azure CLI sign-in. Do not enable keys to work around policy. |
| Other HTTP 401/403 | In key mode, match the key to the endpoint/region. In Entra mode, check the CLI identity and Speech data-plane role. Check networking restrictions as well. |
| Entra sign-in unavailable | Install/sign in with Azure CLI on the server and select the correct subscription. The app reports an authentication failure without sending an audio request. |
| Upload/connection/response timeout | Check the specific timeout category in Request diagnostics. Large recordings need a second upload to Azure. A timed-out request might still have been processed/billed. |
| HTTP 429/502/503/504 | Check Request diagnostics and any `Retry-After`, then use Retry failed requests. Earlier errors remain visible in the history. |
| MAI `diarization_unavailable` | The provider's speaker-labeling stage failed. Disable Identify speakers and start a new matched, transcription-only comparison if speaker labels are not required. |
| MAI rejects M4A | Convert to supported WAV, MP3, or FLAC, or choose Azure Fast. |
| Missing WER/CER or duration | Supply a real reference for error rates. Duration-dependent values stay empty if duration is unavailable. |
| No OpenAI configuration | Transcription still works. Configure the deployment only when using summaries or vision. |
| OpenAI `AuthenticationTypeDisabled` | Set `GPT4o_AUTH_MODE=entra` for the original endpoint/deployment and use an authorized CLI identity. Do not change resource policy. |
| Translator 401/403 with the correct region | Check whether the original resource disables keys. Use explicit Translator Entra mode, its original resource ID and region; do not migrate to another region. |
| No live mic captions / SDK WebSocket 401 | Check `SPEECH_AUTH_MODE`, custom endpoint, Speech data-plane access, and server microphone permission. Read the visible SDK cancellation error. This is separate from MAI file transcription. |
| Capture still stopping | Wait for the worker to confirm shutdown. Clear/Back/new Start cannot bypass incomplete cleanup; a reported native stop failure requires restarting this app process. |
| Upload/theme configuration not applied | Start Streamlit from `meeting_summary` as shown above. |
