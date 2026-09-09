from dataclasses import asdict
import hashlib
from pathlib import Path

import streamlit as st

from . import register_scenario
import llm_analysis
from speech_fast_transcription import (
    AZURE_FAST,
    ENGINE_LABELS,
    MAI_LANGUAGES,
    MAI_TRANSCRIBE,
    MIME_TYPES,
    SPEECH_LANGUAGES,
    TranscriptionOptions,
    get_connection,
    validate_audio,
)
from transcription_benchmark import (
    SCORING_DESCRIPTION,
    TIMING_DESCRIPTION,
    benchmark_audio,
    failed_runs,
    metrics_rows,
    normalize_transcript,
    retry_failed_requests,
    summary_rows,
)

RUN_MODES = {
    "Azure Fast": [AZURE_FAST],
    "MAI-Transcribe-2 (preview)": [MAI_TRANSCRIBE],
    "Compare both": [AZURE_FAST, MAI_TRANSCRIBE],
}


def _render_report(report):
    report_key = report.started_at_utc
    st.divider()
    st.subheader("Saved run results")
    st.caption(
        f"{report.filename} | Started {report.started_at_utc} | "
        f"{report.repetitions} configured repetition(s) per engine | "
        f"{len(report.runs)} recorded attempt(s), including any retries"
    )
    st.dataframe(summary_rows(report), hide_index=True, use_container_width=True)
    st.caption(
        "Request time includes upload, service processing, and download; it is not "
        "model-only inference time. Entra sign-in/token acquisition is excluded. "
        "Medians exclude failed requests. RTF below 1 means "
        "the request completed faster than the audio's duration."
    )
    if not report.reference.strip():
        st.info("Accuracy not scored: no reference transcript was supplied. Missing values are not zero.")
    if MAI_TRANSCRIBE in report.engines and report.options.mai_style == "clean":
        st.warning(
            "MAI used clean style, which intentionally removes fillers. "
            "This changes WER/CER relative to a verbatim reference."
        )
    with st.expander("Per-request measurements", expanded=True):
        st.dataframe(metrics_rows(report), hide_index=True, use_container_width=True)
    current_failures = failed_runs(report)
    for run in current_failures:
        st.error(
            f"{ENGINE_LABELS[run.engine]}, run {run.repetition}, "
            f"attempt {getattr(run, 'attempt', 1)}: {run.error}"
        )
    if any(run.error for run in report.runs):
        st.caption("Earlier failed attempts remain in the table and export, even after a successful retry.")
        with st.expander("Request diagnostics"):
            for run in report.runs:
                if run.error:
                    st.write(
                        f"**{ENGINE_LABELS[run.engine]} - run {run.repetition}, "
                        f"attempt {getattr(run, 'attempt', 1)}**"
                    )
                    st.json({
                        "error": run.error,
                        "http_status": run.status_code,
                        "request_seconds": run.failed_request_seconds,
                        **(getattr(run, "diagnostics", None) or {}),
                    })
    with st.expander("Method and saved configuration"):
        st.write(TIMING_DESCRIPTION)
        st.write(SCORING_DESCRIPTION)
        st.json({
            "audio_sha256": report.audio_sha256,
            "audio_bytes": report.audio_bytes,
            "connections": report.connections,
            "options": asdict(report.options),
        })
        if report.reference.strip():
            st.text_area("Reference used for this run", report.reference, disabled=True, key=f"saved_reference_{report_key}")
    st.download_button(
        "Download complete benchmark (JSON)",
        report.to_json(),
        file_name="avia_transcription_benchmark.json",
        mime="application/json",
        key="audio_download_benchmark",
    )
    st.caption("The JSON contains transcripts, the reference, settings, timings, and raw responses, but no API keys.")

    successful = [index for index, run in enumerate(report.runs) if run.result is not None]
    if not successful:
        st.warning("No successful transcription responses. Resolve the errors before comparing performance.")
        return
    st.subheader("Transcripts")
    # Show both engines at once; repetitions can contain different transcriptions.
    columns = st.columns(len(report.engines))
    for engine, column in zip(report.engines, columns):
        with column:
            st.markdown(f"**{ENGINE_LABELS[engine]}**")
            for index, run in enumerate(report.runs):
                if run.engine != engine or run.result is None:
                    continue
                result = run.result
                attempt_label = f"Run {run.repetition}, attempt {getattr(run, 'attempt', 1)}"
                with st.expander(attempt_label, expanded=run.repetition == 1):
                    locales = ", ".join(result.locales) if result.locales else "Not returned by the service"
                    st.caption(f"Detected language(s): {locales}")
                    if result.text:
                        st.text_area(
                            "Transcript",
                            result.display_text,
                            height=220,
                            disabled=True,
                            key=f"audio_transcript_{report_key}_{index}",
                        )
                    else:
                        st.warning("The request succeeded, but the service returned no speech.")
                    st.download_button(
                        "Download transcript",
                        result.display_text,
                        file_name=f"{engine}_run_{run.repetition}_attempt_{getattr(run, 'attempt', 1)}.txt",
                        mime="text/plain",
                        key=f"audio_download_{index}",
                    )
                    st.json({"request_definition": result.definition, "response": result.raw_response}, expanded=False)

    st.subheader("Optional AI summary")
    st.caption(
        "Summarization is a separate Azure OpenAI request. It is never included in "
        "transcription timings or reference scoring."
    )
    selected = st.selectbox(
        "Transcript to summarize",
        successful,
        format_func=lambda index: (
            f"{ENGINE_LABELS[report.runs[index].engine]} - run {report.runs[index].repetition}, "
            f"attempt {getattr(report.runs[index], 'attempt', 1)}"
        ),
        key=f"audio_summary_source_{report_key}",
    )
    prompt = st.text_area("Custom summary prompt (optional)", key="audio_summary_prompt")
    result = report.runs[selected].result
    if st.button("Generate summary", disabled=not result.text, key="audio_generate_summary"):
        with st.spinner("Summarizing the selected transcript..."):
            try:
                summary = llm_analysis.analysis_text(
                    prompt,
                    result.display_text,
                    result.locales[0] if result.locales else None,
                )
            except (ValueError, llm_analysis.AnalysisError) as exc:
                st.session_state.setdefault("audio_summary_errors", {})[selected] = str(exc)
            else:
                st.session_state.setdefault("audio_summary_errors", {}).pop(selected, None)
                st.session_state.setdefault("audio_summaries", {})[selected] = {
                    "text": summary,
                    "prompt": prompt,
                }
    summary_error = st.session_state.get("audio_summary_errors", {}).get(selected)
    if summary_error:
        st.error(f"Summary failed: {summary_error}")
    saved_summary = st.session_state.get("audio_summaries", {}).get(selected)
    if saved_summary is not None:
        if saved_summary["prompt"].strip() != prompt.strip():
            st.warning("The saved summary used the earlier prompt shown below. Generate again to use the current prompt.")
        st.write(saved_summary["text"])
        st.caption("Prompt used: " + (saved_summary["prompt"] or "Default language-aware summary"))
        st.download_button(
            "Download summary",
            saved_summary["text"],
            file_name="summary.txt",
            mime="text/plain",
            key="audio_download_summary",
        )


@register_scenario(
    key="audio_file_summary",
    title="Audio Transcription Lab",
    description="Transcribe files with Azure Fast or MAI-Transcribe-2, compare measured performance, and optionally summarize.",
    keywords="File audio | MAI preview | Latency | WER / CER | Azure OpenAI summaries",
)
def run():
    mode = st.radio(
        "Transcription engine",
        list(RUN_MODES),
        horizontal=True,
        key="audio_engine_mode",
    )
    engines = RUN_MODES[mode]
    has_mai = MAI_TRANSCRIBE in engines
    if has_mai:
        st.info(
            "MAI-Transcribe-2 is a preview model selected explicitly through the Speech REST API. "
            "This workflow sends completed audio files, not live streaming. "
            "A compatible Speech/Foundry resource and supported region are required."
        )
    st.caption(
        "MAI: WAV, MP3, FLAC. Azure Fast also accepts M4A. "
        "AVIA's file limit is less than 300 MB; the actual codec must be supported by Azure."
    )
    audio_file = st.file_uploader(
        "Audio file",
        type=["wav", "mp3", "flac", "m4a"],
        key="audio_upload",
    )
    audio = audio_file.getvalue() if audio_file is not None else None
    if audio:
        st.audio(audio, format=MIME_TYPES[Path(audio_file.name).suffix.lower()])
        if len(audio) >= 10_000_000:
            st.info(
                "This is a large recording. After the browser upload, AVIA must upload it "
                "again to Azure for each request. Allow time for upload and transcription. "
                "Connection establishment has a 10-second timeout; upload-write and response-read "
                "inactivity timeouts are separately set to 300 seconds."
            )

    languages = MAI_LANGUAGES if engines == [MAI_TRANSCRIBE] else SPEECH_LANGUAGES
    locale = st.selectbox(
        "Spoken language",
        [""] + list(languages),
        format_func=lambda value: f"{languages[value]} ({value})" if value else "Automatic detection",
        key="audio_locale_mai" if engines == [MAI_TRANSCRIBE] else "audio_locale_shared",
        help="For MAI, a language selection is a strong constraint, not a candidate list. Leave automatic for mixed-language audio.",
    )
    if not locale:
        st.caption(
            "Azure Fast auto-detects among AVIA's 7 candidate locales. MAI automatically "
            "handles its 60 supported languages. For a controlled single-language comparison, "
            "select the known language rather than comparing these different detection strategies."
        )
    with st.expander("Transcription settings", expanded=True):
        first, second = st.columns(2)
        with first:
            diarization = st.checkbox(
                "Identify speakers (diarization)",
                value=True,
                key="audio_diarization",
                help="Requests speaker-labeled segments. No speaker-count or speaker-accuracy metric is inferred.",
            )
            profanity = st.selectbox(
                "Profanity filtering",
                ["Masked", "None", "Removed", "Tags"],
                key="audio_profanity",
                help="Filtering changes transcript text and therefore reference error rates.",
            )
        with second:
            style = st.selectbox(
                "MAI transcript style",
                ["verbatim", "clean"],
                disabled=not has_mai,
                key="audio_mai_style",
                help="Verbatim preserves fillers and false starts. Clean removes them. Azure Fast uses its default display text.",
            )
            timestamps = st.selectbox(
                "MAI timestamp detail",
                ["word", "segment", "none"],
                disabled=not has_mai,
                key="audio_mai_timestamps",
                help="Azure Fast returns word timings by default. Use word for a closer feature comparison.",
            )
    options = TranscriptionOptions(
        locale=locale or None,
        diarization=diarization,
        profanity_filter=profanity,
        mai_style=style,
        mai_timestamps=timestamps,
    )
    reference = st.text_area(
        "Reference transcript (optional, for WER / CER)",
        key="audio_reference",
        placeholder="Paste the known spoken words without timestamps or speaker labels.",
        help="No reference means no accuracy score. Use CER for Chinese, Japanese, and other languages without word spaces.",
    )
    repetitions = st.number_input(
        "Requests per engine",
        min_value=1,
        max_value=5,
        value=1,
        step=1,
        key="audio_repetitions",
    )
    st.caption(
        f"This run sends up to {len(engines) * repetitions} request(s); Azure charges may apply. "
        "Requests run sequentially, alternate engine order across repeats, and are not "
        "cached or automatically retried. One clip cannot establish a general model ranking."
    )

    errors = []
    if reference.strip() and not normalize_transcript(reference):
        errors.append("The reference must contain text, not just punctuation.")
    if audio is not None:
        for engine in engines:
            try:
                validate_audio(audio, audio_file.name, engine)
            except ValueError as exc:
                errors.append(str(exc))
    with st.expander("Connection and API setup"):
        st.caption(
            "Configuration presence/format only, not a connectivity check. "
            "Credentials are read from meeting_summary/.env; no OpenAI key is needed for transcription."
        )
        for engine in engines:
            try:
                connection = get_connection(engine)
            except ValueError as exc:
                errors.append(f"{ENGINE_LABELS[engine]}: {exc}")
            else:
                st.write(f"**{ENGINE_LABELS[engine]}**")
                st.json(connection.metadata())
        st.write(
            "Both engines use the SPEECH_* configuration by default. Set SPEECH_AUTH_MODE=entra "
            "and SPEECH_ENDPOINT=https://<resource>.cognitiveservices.azure.com for Microsoft "
            "Entra ID via the server's Azure CLI sign-in. Your identity needs the Cognitive "
            "Services Speech User role or equivalent data-plane access. API keys are not used "
            "in Entra mode. Key mode requires SPEECH_KEY and an endpoint or matching region."
        )
        st.write(
            "For a separate MAI resource, use MAI_SPEECH_AUTH_MODE and MAI_SPEECH_ENDPOINT "
            "(plus MAI_SPEECH_KEY in key mode). Overrides must form a complete configuration. "
            "Entra sign-in is local to the computer running Streamlit, not the browser visitor."
        )
        st.markdown(
            "[MAI-Transcribe-2 API and languages](https://learn.microsoft.com/azure/ai-services/speech-service/mai-transcribe) "
            "| [Region availability](https://learn.microsoft.com/azure/ai-services/speech-service/regions?tabs=llmspeech) "
            "| [Speech Entra access](https://learn.microsoft.com/azure/ai-services/speech-service/role-based-access-control)"
        )
    for error in dict.fromkeys(errors):
        st.warning(error)

    if st.button(
        "Run comparison" if len(engines) > 1 else "Transcribe audio",
        type="primary",
        disabled=audio is None or bool(errors),
        key="audio_run",
    ):
        progress = st.progress(0.0)

        def update_progress(completed, total, label):
            progress.progress(completed / total, text=f"{completed}/{total} requests complete - {label}")

        with st.spinner("Uploading audio to Azure and waiting for transcription..."):
            try:
                report = benchmark_audio(
                    audio,
                    audio_file.name,
                    engines,
                    options,
                    repetitions=repetitions,
                    reference=reference,
                    on_progress=update_progress,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state["audio_report"] = report
                st.session_state["audio_summaries"] = {}
                st.session_state["audio_summary_errors"] = {}
        progress.empty()

    report = st.session_state.get("audio_report")
    if report is not None:
        same_inputs = (
            audio is not None
            and report.audio_sha256 == hashlib.sha256(audio).hexdigest()
            and report.filename == audio_file.name
            and report.engines == engines
            and asdict(report.options) == asdict(options)
            and report.repetitions == repetitions
            and report.reference == reference
        )
        if not same_inputs:
            st.warning(
                "Inputs have changed. The saved results below still belong to the filename "
                "and settings recorded in that run, not the current controls. Run again to update them."
            )
        if failed_runs(report):
            st.caption(
                "Retry only the failed entries with the saved audio/settings. Successful results "
                "and earlier failures are kept. Retrying sends additional, potentially billable requests."
            )
            if st.button("Retry failed requests", disabled=not same_inputs, key="audio_retry"):
                retry_progress = st.progress(0.0)

                def update_retry_progress(completed, total, label):
                    retry_progress.progress(
                        completed / total, text=f"{completed}/{total} retries complete - {label}"
                    )

                with st.spinner("Retrying failed requests: uploading audio and waiting for Azure..."):
                    try:
                        report = retry_failed_requests(report, audio, on_progress=update_retry_progress)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["audio_report"] = report
                retry_progress.empty()
        _render_report(report)
