"""Offline KWS validation for positive, negative, and playback self-trigger WAVs.

The acceptance corpus is recorded separately with record_cases.py. This script
never opens a microphone; it deterministically replays every WAV into the KWS
model and writes a JSON report.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import config  # noqa: E402
import voice_models  # noqa: E402

CANDIDATE_DIRS = {
    "小屋小屋": "xiaowu-xiaowu",
    "你好小屋": "nihao-xiaowu",
}
AUDIO_SUFFIXES = {".wav", ".flac"}


def build_spotter(keywords_file: Path) -> sherpa_onnx.KeywordSpotter:
    paths = config.kws_paths()
    return sherpa_onnx.KeywordSpotter(
        tokens=str(paths["tokens"]),
        encoder=str(paths["encoder"]),
        decoder=str(paths["decoder"]),
        joiner=str(paths["joiner"]),
        keywords_file=str(keywords_file),
        num_threads=2,
        provider="cpu",
        keywords_score=2.0,
        keywords_threshold=0.25,
        num_trailing_blanks=1,
    )


def audio_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)


def detect(
    spotter: sherpa_onnx.KeywordSpotter,
    wav: Path,
    recognizer: sherpa_onnx.OfflineRecognizer | None = None,
    forbidden_terms: tuple[str, ...] = (),
) -> dict:
    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = np.asarray(samples, dtype=np.float32)
    stream = spotter.create_stream()
    detections = []
    t0 = time.perf_counter()

    # Feed incrementally. If a keyword is found, reset only the decoder state
    # and continue with later audio; feeding a whole 30-minute file before the
    # first reset could otherwise discard the unprocessed remainder.
    chunk_size = max(1, int(0.1 * sample_rate))
    padded = np.concatenate([samples, np.zeros(int(0.8 * sample_rate), dtype=np.float32)])
    for start in range(0, len(padded), chunk_size):
        stream.accept_waveform(sample_rate, padded[start : start + chunk_size])
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            result = spotter.get_result(stream)
            if result:
                detections.append(result)
                spotter.reset_stream(stream)
    stream.input_finished()
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        result = spotter.get_result(stream)
        if result:
            detections.append(result)
            spotter.reset_stream(stream)
    row = {
        "wav": str(wav),
        "audio_seconds": round(len(samples) / sample_rate, 3),
        "detections": detections,
        "kws_seconds": round(time.perf_counter() - t0, 3),
    }
    if recognizer is not None:
        transcript = voice_models.transcribe(recognizer, samples, sample_rate)
        hits = [term for term in forbidden_terms if term and term in transcript]
        row["asr_transcript"] = transcript
        row["forbidden_term_hits"] = hits
    return row


def corpus_complete(rows: list[dict], min_files: int, min_seconds: float) -> bool:
    return len(rows) >= min_files and sum(float(r.get("audio_seconds", 0.0)) for r in rows) >= min_seconds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keywords-file", type=Path, default=Path("tools/voice-check/cases/wake-keywords.txt"))
    parser.add_argument("--positives-root", type=Path, default=Path("tools/voice-check/cases/audio/wake"))
    parser.add_argument("--positives", type=int, default=20, help="required clips per candidate")
    parser.add_argument("--min-positive-hits", type=int, default=18, help="required detections per candidate")
    parser.add_argument("--negatives-dir", type=Path, default=Path("tools/voice-check/cases/noise-30min"))
    parser.add_argument("--negative-min-seconds", type=float, default=1800.0)
    parser.add_argument(
        "--self-trigger-dir",
        "--self-trigger-out",
        dest="self_trigger_dir",
        type=Path,
        default=Path("tools/voice-check/cases/self-trigger"),
        help="directory containing microphone recordings of system playback",
    )
    parser.add_argument("--self-trigger-min-files", type=int, default=1)
    parser.add_argument("--self-trigger-min-seconds", type=float, default=1.0)
    parser.add_argument(
        "--forbidden-terms",
        default="小屋小屋,你好小屋,打开,关闭,调到,调成,播报",
        help="comma-separated ASR terms forbidden in playback captures",
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--no-gate", action="store_true", help="smoke mode; missing corpus does not fail")
    args = parser.parse_args()

    spotter = build_spotter(args.keywords_file)
    candidates = {}
    positive_complete = True
    for phrase, dirname in CANDIDATE_DIRS.items():
        files = audio_files(args.positives_root / dirname)
        rows = []
        success = 0
        for wav in files:
            row = detect(spotter, wav)
            row["expected"] = phrase
            row["hit"] = phrase in row["detections"]
            success += int(row["hit"])
            rows.append(row)
            print(f"[{'HIT ' if row['hit'] else 'MISS'}] {phrase} {wav.name}: {row['detections']}")
        complete = len(files) >= args.positives
        positive_complete &= complete
        candidates[phrase] = {
            "directory": str(args.positives_root / dirname),
            "clips": len(files),
            "required": args.positives,
            "success": success,
            "min_hits": args.min_positive_hits,
            "passed": complete and success >= args.min_positive_hits,
            "results": rows,
        }

    negative_rows = []
    for wav in audio_files(args.negatives_dir):
        row = detect(spotter, wav)
        negative_rows.append(row)
        if row["detections"]:
            print(f"[FALSE WAKE] negative {wav.name}: {row['detections']}")
    false_wakes = sum(len(r["detections"]) for r in negative_rows)
    negative_seconds = round(sum(r["audio_seconds"] for r in negative_rows), 3)
    negative_complete = corpus_complete(negative_rows, min_files=1, min_seconds=args.negative_min_seconds)

    self_files = audio_files(args.self_trigger_dir)
    forbidden_terms = tuple(x.strip() for x in args.forbidden_terms.split(",") if x.strip())
    self_recognizer = voice_models.create_asr() if self_files else None
    self_rows = []
    for wav in self_files:
        row = detect(spotter, wav, self_recognizer, forbidden_terms)
        self_rows.append(row)
        if row["detections"] or row.get("forbidden_term_hits"):
            print(
                f"[SELF TRIGGER] {wav.name}: kws={row['detections']} "
                f"asr_hits={row.get('forbidden_term_hits', [])} transcript={row.get('asr_transcript', '')}"
            )
    self_triggers = sum(len(r["detections"]) for r in self_rows)
    self_command_hits = sum(len(r.get("forbidden_term_hits", [])) for r in self_rows)
    self_seconds = round(sum(r["audio_seconds"] for r in self_rows), 3)
    self_complete = corpus_complete(self_rows, args.self_trigger_min_files, args.self_trigger_min_seconds)

    passed = (
        positive_complete
        and all(x["passed"] for x in candidates.values())
        and negative_complete
        and self_complete
        and self_triggers == 0
        and self_command_hits == 0
    )
    report = {
        "tool": "check_wake.py",
        "model_root": str(config.models_dir()),
        "candidates": candidates,
        "negative": {
            "directory": str(args.negatives_dir),
            "files": len(negative_rows),
            "audio_seconds": negative_seconds,
            "required_seconds": args.negative_min_seconds,
            "corpus_complete": negative_complete,
            "false_wakes": false_wakes,
            "false_wake_hard_gate": False,
            "duration_hard_gate": True,
            "results": negative_rows,
        },
        "self_trigger": {
            "directory": str(args.self_trigger_dir),
            "files": len(self_rows),
            "required_files": args.self_trigger_min_files,
            "audio_seconds": self_seconds,
            "required_seconds": args.self_trigger_min_seconds,
            "corpus_complete": self_complete,
            "kws_detections": self_triggers,
            "asr_forbidden_term_hits": self_command_hits,
            "forbidden_terms": forbidden_terms,
            "hard_gate": True,
            "results": self_rows,
        },
        "passed": None if args.no_gate else passed,
        "note": (
            f"Each candidate requires >={args.min_positive_hits}/{args.positives}; "
            f"negative corpus duration must be >={args.negative_min_seconds}s (false-wake count is report-only); "
            "self-trigger corpus must be non-empty and have zero KWS detections and zero forbidden ASR terms."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"candidates clips={sum(x['clips'] for x in candidates.values())}, "
        f"negative={negative_seconds:.1f}/{args.negative_min_seconds:.1f}s false_wakes={false_wakes}, "
        f"self_trigger={len(self_rows)} files {self_seconds:.1f}s "
        f"kws={self_triggers} asr_hits={self_command_hits}"
    )
    print(f"wrote {args.out}")
    if args.no_gate:
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
