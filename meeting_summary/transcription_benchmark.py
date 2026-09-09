"""Reproducible client-side timing and reference-based transcription scoring."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import median
import time
from typing import Callable, Optional
import unicodedata

from rapidfuzz.distance import Levenshtein

from speech_fast_transcription import (
    ENGINE_LABELS,
    TranscriptionError,
    TranscriptionOptions,
    TranscriptionResult,
    build_definition,
    get_connection,
    transcribe_audio,
    validate_audio,
)

SCORING_DESCRIPTION = (
    "Unicode NFKC + casefold; remove Unicode punctuation; collapse whitespace. "
    "WER uses whitespace-delimited words. CER excludes whitespace and uses Unicode "
    "code points. Both are edit distance / reference length, not model confidence, "
    "and can exceed 100%. Numbers and spelling variants are not normalized. "
    "Prefer CER for languages without word spaces. Speaker labels are not scored."
)
TIMING_DESCRIPTION = (
    "At most one synchronous HTTP request per engine per repetition, with identical audio bytes. "
    "Initial sequential calls alternate engine order each repetition. No automatic retries, model "
    "fallbacks, response caching, or discarded warm-ups. Client request time includes "
    "upload, service processing, and download, but excludes Entra token acquisition, "
    "scoring, UI, and summaries. Authentication failures have no HTTP request time. "
    "RTF = request seconds / audio seconds (lower is better); audio speed is its inverse. "
    "Duration uses the WAV header when readable, otherwise the service's top-level "
    "durationMilliseconds, never the last speech segment. Failed requests are excluded "
    "from medians and counted separately. Explicit retries add numbered attempts for failed "
    "entries only; earlier failures remain in the report. Successful-request medians do not "
    "include failed-request time or the wait before a manual retry. "
    "This is not a service-only inference benchmark."
)


@dataclass(frozen=True)
class AccuracyScores:
    word_error_rate: float
    character_error_rate: float
    word_edits: int
    character_edits: int
    reference_words: int
    reference_characters: int


@dataclass
class BenchmarkRun:
    engine: str
    repetition: int
    result: Optional[TranscriptionResult] = None
    accuracy: Optional[AccuracyScores] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    failed_request_seconds: Optional[float] = None
    attempt: int = 1
    diagnostics: Optional[dict] = None


@dataclass
class BenchmarkReport:
    filename: str
    audio_sha256: str
    audio_bytes: int
    engines: list[str]
    repetitions: int
    options: TranscriptionOptions
    reference: str
    started_at_utc: str
    connections: dict
    runs: list[BenchmarkRun] = field(default_factory=list)
    schema_version: int = 2
    scoring_method: str = SCORING_DESCRIPTION
    timing_method: str = TIMING_DESCRIPTION

    def to_json(self):
        data = asdict(self)
        data["per_request_metrics"] = metrics_rows(self)
        data["summary"] = summary_rows(self)
        return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)


def normalize_transcript(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(
        "".join(ch for ch in normalized if not unicodedata.category(ch).startswith("P")).split()
    )


def score_transcript(reference: str, hypothesis: str) -> AccuracyScores:
    normalized_reference = normalize_transcript(reference)
    if not normalized_reference:
        raise ValueError("The reference must contain text, not just whitespace or punctuation.")
    normalized_hypothesis = normalize_transcript(hypothesis)
    reference_words, hypothesis_words = normalized_reference.split(), normalized_hypothesis.split()
    reference_chars = "".join(normalized_reference.split())
    hypothesis_chars = "".join(normalized_hypothesis.split())
    word_edits = Levenshtein.distance(reference_words, hypothesis_words)
    char_edits = Levenshtein.distance(reference_chars, hypothesis_chars)
    return AccuracyScores(
        word_error_rate=word_edits / len(reference_words),
        character_error_rate=char_edits / len(reference_chars),
        word_edits=word_edits,
        character_edits=char_edits,
        reference_words=len(reference_words),
        reference_characters=len(reference_chars),
    )


def _execute_attempt(audio, filename, engine, options, connection, reference, repetition, attempt=1):
    run = BenchmarkRun(engine=engine, repetition=repetition, attempt=attempt)
    try:
        run.result = transcribe_audio(audio, filename, engine, options, connection)
    except TranscriptionError as exc:
        run.error = str(exc)
        run.status_code = exc.status_code
        run.failed_request_seconds = exc.request_seconds
        run.diagnostics = exc.diagnostics
    else:
        run.status_code = 200
        if reference.strip():
            run.accuracy = score_transcript(reference, run.result.text)
    return run


def failed_runs(report: BenchmarkReport) -> list[BenchmarkRun]:
    latest = {}
    for run in report.runs:
        latest[(run.engine, run.repetition)] = run
    return [run for run in latest.values() if run.error is not None]


def benchmark_audio(
    audio: bytes,
    filename: str,
    engines: list[str],
    options: TranscriptionOptions,
    repetitions: int = 1,
    reference: str = "",
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> BenchmarkReport:
    if not engines or len(set(engines)) != len(engines):
        raise ValueError("Select at least one engine, without duplicates.")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= 5:
        raise ValueError("Choose between one and five repetitions.")
    if reference.strip():
        score_transcript(reference, "")
    connections = {}
    for engine in engines:
        validate_audio(audio, filename, engine)
        build_definition(engine, options)
        connections[engine] = get_connection(engine)
    report = BenchmarkReport(
        filename=filename,
        audio_sha256=hashlib.sha256(audio).hexdigest(),
        audio_bytes=len(audio),
        engines=engines.copy(),
        repetitions=repetitions,
        options=options,
        reference=reference,
        started_at_utc=datetime.now(timezone.utc).isoformat(),
        connections={engine: connection.metadata() for engine, connection in connections.items()},
    )
    total = len(engines) * repetitions
    for index in range(repetitions):
        order = engines if index % 2 == 0 else list(reversed(engines))
        for engine in order:
            if on_progress:
                on_progress(len(report.runs), total, ENGINE_LABELS[engine])
            report.runs.append(_execute_attempt(
                audio, filename, engine, options, connections[engine], reference, index + 1
            ))
    if on_progress:
        on_progress(total, total, "Finished")
    return report


def retry_failed_requests(
    report: BenchmarkReport,
    audio: bytes,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> BenchmarkReport:
    pending = failed_runs(report)
    if not pending:
        raise ValueError("There are no failed requests to retry.")
    if hashlib.sha256(audio).hexdigest() != report.audio_sha256:
        raise ValueError("Retry requires the exact audio file used in the saved run.")
    connections = {}
    for run in pending:
        validate_audio(audio, report.filename, run.engine)
        build_definition(run.engine, report.options)
        connection = get_connection(run.engine)
        if connection.metadata() != report.connections[run.engine]:
            raise ValueError("Connection settings changed. Start a new run instead of retrying this report.")
        connections[run.engine] = connection
        diagnostics = getattr(run, "diagnostics", None) or {}
        deadline = diagnostics.get("retry_not_before")
        if deadline is not None and deadline > time.time():
            wait = math.ceil(deadline - time.time())
            raise ValueError(f"The service requested a pause. Wait approximately {wait} seconds before retrying.")
    updated = BenchmarkReport(
        filename=report.filename,
        audio_sha256=report.audio_sha256,
        audio_bytes=report.audio_bytes,
        engines=report.engines.copy(),
        repetitions=report.repetitions,
        options=report.options,
        reference=report.reference,
        started_at_utc=report.started_at_utc,
        connections=report.connections.copy(),
        runs=report.runs.copy(),
        scoring_method=report.scoring_method,
    )
    for index, previous in enumerate(pending):
        if on_progress:
            on_progress(index, len(pending), ENGINE_LABELS[previous.engine])
        updated.runs.append(_execute_attempt(
            audio, report.filename, previous.engine, report.options,
            connections[previous.engine], report.reference, previous.repetition,
            getattr(previous, "attempt", 1) + 1,
        ))
    if on_progress:
        on_progress(len(pending), len(pending), "Finished")
    return updated


def metrics_rows(report: BenchmarkReport) -> list[dict]:
    rows = []
    for run in report.runs:
        result = run.result
        rows.append({
            "Engine": ENGINE_LABELS[run.engine],
            "Run": run.repetition,
            "Attempt": getattr(run, "attempt", 1),
            "Status": "Failed" if run.error else "No speech" if not result.text else "Succeeded",
            "Request (s)": result.request_seconds if result else run.failed_request_seconds,
            "Audio (s)": result.audio_seconds if result else None,
            "RTF": result.real_time_factor if result else None,
            "Audio speed (x)": result.audio_speed if result else None,
            "WER (%)": run.accuracy.word_error_rate * 100 if run.accuracy else None,
            "CER (%)": run.accuracy.character_error_rate * 100 if run.accuracy else None,
            "Duration source": result.duration_source if result else None,
            "Error": run.error,
        })
    return rows


def summary_rows(report: BenchmarkReport) -> list[dict]:
    rows = []
    for engine in report.engines:
        runs = [run for run in report.runs if run.engine == engine]
        results = [run.result for run in runs if run.result is not None]
        factors = [result.real_time_factor for result in results if result.real_time_factor is not None]
        rows.append({
            "Engine": ENGINE_LABELS[engine],
            "Successful requests": len(results),
            "Failed attempts": sum(run.error is not None for run in runs),
            "Empty transcripts": sum(not result.text for result in results),
            "Median request (s)": median(result.request_seconds for result in results) if results else None,
            "Median RTF": median(factors) if factors else None,
        })
    return rows
