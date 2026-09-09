import json
from dataclasses import replace
import unittest
from unittest.mock import patch

from speech_fast_transcription import AZURE_FAST, MAI_TRANSCRIBE, TranscriptionError, TranscriptionOptions
from tests.helpers import TEST_CONNECTION, transcription, wav_audio
from transcription_benchmark import (
    benchmark_audio, failed_runs, metrics_rows, retry_failed_requests, score_transcript, summary_rows,
)


class AccuracyTests(unittest.TestCase):
    def test_normalization(self):
        scores = score_transcript("  HELLO,   world! ", "hello world")
        self.assertEqual(scores.word_error_rate, 0)
        self.assertEqual(scores.character_error_rate, 0)
        self.assertEqual(score_transcript("\uff21\uff22\uff23", "abc").word_error_rate, 0)

    def test_edit_counts_and_reference_denominators(self):
        scores = score_transcript("one two three", "one three")
        self.assertEqual(scores.word_edits, 1)
        self.assertEqual(scores.reference_words, 3)
        self.assertAlmostEqual(scores.word_error_rate, 1 / 3)
        self.assertAlmostEqual(score_transcript("abc", "adc").character_error_rate, 1 / 3)

    def test_cer_for_unsegmented_languages(self):
        scores = score_transcript("\u4f60\u597d\u4e16\u754c", "\u4f60\u597d\u4e16\u4eba")
        self.assertEqual(scores.character_error_rate, 0.25)
        self.assertEqual(scores.word_error_rate, 1)

    def test_empty_hypothesis_is_all_deletions(self):
        scores = score_transcript("known words", "")
        self.assertEqual(scores.word_error_rate, 1)
        self.assertEqual(scores.character_error_rate, 1)

    def test_rates_can_exceed_one_hundred_percent(self):
        scores = score_transcript("a", "a b c")
        self.assertEqual(scores.word_error_rate, 2)
        self.assertEqual(scores.character_error_rate, 2)

    def test_empty_or_punctuation_only_reference_is_rejected(self):
        for reference in ("", "  ", ".,!?"):
            with self.subTest(reference=reference):
                with self.assertRaises(ValueError):
                    score_transcript(reference, "words")


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.connection = patch("transcription_benchmark.get_connection", return_value=TEST_CONNECTION).start()
        self.transcribe = patch("transcription_benchmark.transcribe_audio").start()
        self.transcribe.side_effect = (
            lambda audio, filename, engine, options, connection: transcription(engine)
        )
        self.addCleanup(patch.stopall)

    def test_identical_audio_alternating_order_and_exact_request_count(self):
        audio = wav_audio()
        progress = []
        report = benchmark_audio(
            audio, "sample.wav", [AZURE_FAST, MAI_TRANSCRIBE], TranscriptionOptions(),
            repetitions=3, reference="Hello world.",
            on_progress=lambda done, total, label: progress.append((done, total)),
        )
        calls = self.transcribe.call_args_list
        self.assertEqual([call.args[2] for call in calls], [
            AZURE_FAST, MAI_TRANSCRIBE, MAI_TRANSCRIBE, AZURE_FAST, AZURE_FAST, MAI_TRANSCRIBE,
        ])
        self.assertTrue(all(call.args[0] is audio for call in calls))
        self.assertEqual(len(report.runs), 6)
        self.assertEqual(progress[-1], (6, 6))
        self.assertTrue(all(run.accuracy.word_error_rate == 0 for run in report.runs))
        row = metrics_rows(report)[0]
        self.assertEqual(row["RTF"], 0.2)
        self.assertEqual(row["Audio speed (x)"], 5)

    def test_failure_does_not_erase_other_engine_and_is_not_counted_in_median(self):
        self.transcribe.side_effect = [
            transcription(AZURE_FAST, seconds=2),
            TranscriptionError("HTTP 429", status_code=429, request_seconds=0.5),
        ]
        report = benchmark_audio(
            wav_audio(), "sample.wav", [AZURE_FAST, MAI_TRANSCRIBE], TranscriptionOptions()
        )
        self.assertEqual(self.transcribe.call_count, 2)
        rows = summary_rows(report)
        self.assertEqual(rows[0]["Median request (s)"], 2)
        self.assertEqual(rows[1]["Failed attempts"], 1)
        self.assertIsNone(rows[1]["Median request (s)"])
        self.assertEqual(metrics_rows(report)[1]["Request (s)"], 0.5)
        self.assertIsNone(metrics_rows(report)[1]["WER (%)"])
        self.assertEqual(report.runs[1].status_code, 429)

    def test_no_reference_means_no_accuracy_not_zero(self):
        report = benchmark_audio(wav_audio(), "sample.wav", [MAI_TRANSCRIBE], TranscriptionOptions())
        self.assertIsNone(report.runs[0].accuracy)
        self.assertIsNone(metrics_rows(report)[0]["WER (%)"])
        self.assertIsNone(metrics_rows(report)[0]["CER (%)"])

    def test_authentication_failure_has_no_fabricated_http_time(self):
        self.transcribe.side_effect = TranscriptionError("Entra sign-in unavailable")
        report = benchmark_audio(wav_audio(), "sample.wav", [MAI_TRANSCRIBE], TranscriptionOptions())
        self.assertIsNone(metrics_rows(report)[0]["Request (s)"])
        self.assertIsNone(summary_rows(report)[0]["Median request (s)"])
        self.assertEqual(summary_rows(report)[0]["Failed attempts"], 1)

    def test_export_contains_reproducible_metadata_but_not_credentials(self):
        report = benchmark_audio(
            wav_audio(), "sample.wav", [MAI_TRANSCRIBE], TranscriptionOptions(), reference="Hello world."
        )
        exported = report.to_json()
        data = json.loads(exported)
        self.assertNotIn(TEST_CONNECTION.key, exported)
        self.assertEqual(len(data["audio_sha256"]), 64)
        self.assertEqual(data["options"]["mai_style"], "verbatim")
        self.assertEqual(data["per_request_metrics"][0]["WER (%)"], 0)
        self.assertIn("raw_response", data["runs"][0]["result"])

    def test_all_configuration_is_validated_before_first_request(self):
        self.connection.side_effect = [TEST_CONNECTION, ValueError("MAI resource missing")]
        with self.assertRaises(ValueError):
            benchmark_audio(wav_audio(), "sample.wav", [AZURE_FAST, MAI_TRANSCRIBE], TranscriptionOptions())
        self.transcribe.assert_not_called()

    def test_manual_retry_only_repeats_failed_entries_and_keeps_history(self):
        self.transcribe.side_effect = [
            transcription(AZURE_FAST, seconds=2),
            TranscriptionError("HTTP 503", status_code=503, request_seconds=1,
                               diagnostics={"apim-request-id": "failed-request"}),
            transcription(MAI_TRANSCRIBE, seconds=3),
        ]
        audio = wav_audio()
        report = benchmark_audio(audio, "sample.wav", [AZURE_FAST, MAI_TRANSCRIBE], TranscriptionOptions())
        recovered = retry_failed_requests(report, audio)
        self.assertEqual(self.transcribe.call_count, 3)
        self.assertEqual(self.transcribe.call_args.args[2], MAI_TRANSCRIBE)
        self.assertEqual(len(report.runs), 2)
        self.assertEqual(len(recovered.runs), 3)
        self.assertIs(recovered.runs[0].result, report.runs[0].result)
        self.assertEqual(recovered.runs[-1].attempt, 2)
        self.assertEqual(failed_runs(recovered), [])
        self.assertEqual(summary_rows(recovered)[1]["Failed attempts"], 1)
        self.assertEqual(summary_rows(recovered)[1]["Median request (s)"], 3)
        exported = json.loads(recovered.to_json())
        self.assertEqual(exported["runs"][1]["diagnostics"]["apim-request-id"], "failed-request")
        self.assertEqual([row["Attempt"] for row in exported["per_request_metrics"]], [1, 1, 2])

    def test_repeated_manual_retry_uses_latest_failure_and_numbers_attempts(self):
        self.transcribe.side_effect = [
            TranscriptionError("503", status_code=503),
            TranscriptionError("503", status_code=503),
            transcription(MAI_TRANSCRIBE),
        ]
        audio = wav_audio()
        report = benchmark_audio(audio, "sample.wav", [MAI_TRANSCRIBE], TranscriptionOptions())
        report = retry_failed_requests(report, audio)
        self.assertEqual(len(failed_runs(report)), 1)
        report = retry_failed_requests(report, audio)
        self.assertEqual([run.attempt for run in report.runs], [1, 2, 3])
        self.assertEqual(failed_runs(report), [])

    def test_manual_retry_rejects_different_audio_or_changed_connection(self):
        self.transcribe.side_effect = TranscriptionError("503", status_code=503)
        audio = wav_audio()
        report = benchmark_audio(audio, "sample.wav", [MAI_TRANSCRIBE], TranscriptionOptions())
        self.transcribe.reset_mock()
        with self.assertRaisesRegex(ValueError, "exact audio"):
            retry_failed_requests(report, b"different audio")
        self.connection.return_value = replace(TEST_CONNECTION, region="westus")
        with self.assertRaisesRegex(ValueError, "Connection settings changed"):
            retry_failed_requests(report, audio)
        self.transcribe.assert_not_called()

    def test_manual_retry_honors_retry_after_without_issuing_requests_or_sleeping(self):
        self.transcribe.side_effect = [
            TranscriptionError("503", status_code=503, diagnostics={"retry_not_before": 1010}),
            transcription(MAI_TRANSCRIBE),
        ]
        audio = wav_audio()
        report = benchmark_audio(audio, "sample.wav", [MAI_TRANSCRIBE], TranscriptionOptions())
        with patch("transcription_benchmark.time.time", return_value=1000):
            with self.assertRaisesRegex(ValueError, "10 seconds"):
                retry_failed_requests(report, audio)
        self.assertEqual(self.transcribe.call_count, 1)
        with patch("transcription_benchmark.time.time", return_value=1011):
            recovered = retry_failed_requests(report, audio)
        self.assertEqual(self.transcribe.call_count, 2)
        self.assertEqual(failed_runs(recovered), [])

    def test_successful_report_has_nothing_to_retry(self):
        audio = wav_audio()
        report = benchmark_audio(audio, "sample.wav", [MAI_TRANSCRIBE], TranscriptionOptions())
        self.transcribe.reset_mock()
        with self.assertRaisesRegex(ValueError, "no failed requests"):
            retry_failed_requests(report, audio)
        self.transcribe.assert_not_called()

    def test_invalid_benchmark_input_never_transcribes(self):
        for engines, repetitions, reference in (
            ([], 1, ""),
            ([MAI_TRANSCRIBE, MAI_TRANSCRIBE], 1, ""),
            ([MAI_TRANSCRIBE], 0, ""),
            ([MAI_TRANSCRIBE], 6, ""),
            ([MAI_TRANSCRIBE], True, ""),
            ([MAI_TRANSCRIBE], 1, "..."),
        ):
            with self.subTest(engines=engines, repetitions=repetitions):
                with self.assertRaises(ValueError):
                    benchmark_audio(wav_audio(), "sample.wav", engines, TranscriptionOptions(), repetitions, reference)
        self.transcribe.assert_not_called()
