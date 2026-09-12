from __future__ import annotations

from check_tts import generation_complete
from check_wake import corpus_complete
from listen_tts import listening_gate


def test_empty_negative_corpus_never_counts_as_complete():
    assert not corpus_complete([], min_files=1, min_seconds=1800)


def test_short_negative_corpus_does_not_satisfy_thirty_minutes():
    rows = [{"audio_seconds": 1799.9}]
    assert not corpus_complete(rows, min_files=1, min_seconds=1800)


def test_negative_corpus_requires_a_real_file_even_with_zero_duration_gate():
    assert not corpus_complete([], min_files=1, min_seconds=0)


def test_complete_corpus_meets_file_and_duration_constraints():
    rows = [{"audio_seconds": 900}, {"audio_seconds": 901}]
    assert corpus_complete(rows, min_files=1, min_seconds=1800)


def test_tts_generation_fails_when_any_case_has_no_audio():
    rows = [
        {"wav": "one.wav", "error": None},
        {"wav": None, "error": "no audio"},
    ]
    assert not generation_complete(rows, case_count=2)


def test_tts_generation_passes_only_when_every_case_succeeds():
    rows = [
        {"wav": "one.wav", "error": None},
        {"wav": "two.wav", "error": None},
    ]
    assert generation_complete(rows, case_count=2)


def test_tts_listening_gate_is_eighteen_of_twenty_but_requires_all_scored():
    eighteen_pass = [{"passed": True}] * 18 + [{"passed": False}] * 2
    assert listening_gate(eighteen_pass, required=20, min_passed=18)
    assert not listening_gate(eighteen_pass[:18], required=20, min_passed=18)
    assert not listening_gate([{"passed": True}] * 17 + [{"passed": False}] * 3, required=20, min_passed=18)
