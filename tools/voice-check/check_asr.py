"""Offline ASR check: transcribe WAV files and report keyword hits.

Phase A5. Reads a TSV of cases (id, wav path, expected key information), runs
sherpa-onnx SenseVoice int8 on CPU, and reports per-case transcription plus
whether every expected token appears in the transcription (order-insensitive).

Usage:
    python check_asr.py --cases tools/voice-check/cases/asr-30.tsv \
        --out docs/superpowers/reports/artifacts/asr-results.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import sherpa_onnx

# The Windows console defaults to GBK; force UTF-8 so CJK transcripts print
# instead of raising UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import config  # noqa: E402


def build_recognizer() -> sherpa_onnx.OfflineRecognizer:
    paths = config.asr_paths()
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(paths["model"]),
        tokens=str(paths["tokens"]),
        num_threads=2,
        use_itn=True,
        language="zh",
        provider="cpu",
        debug=False,
    )


def read_wav(path: Path):
    import soundfile as sf

    samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if sample_rate != config.SAMPLE_RATE:
        raise ValueError(
            f"{path}: expected {config.SAMPLE_RATE} Hz mono 16-bit WAV, got {sample_rate} Hz"
        )
    return samples


def normalize(text: str) -> str:
    """Strip punctuation and whitespace so keyword matching is robust."""
    drop = set("，。、！？.,!?;: 　\n\r\t“”\"'（）()《》-—…")
    return "".join(ch for ch in text if ch not in drop)


def match_expected(transcript: str, expected_groups: list[str]) -> tuple[dict[str, str | None], list[str]]:
    """Match required concepts, allowing `a|b` equivalent surface forms."""
    flat = normalize(transcript)
    missing = []
    matched = {}
    for group in expected_groups:
        alternatives = [item for item in group.split("|") if item]
        found = next((item for item in alternatives if normalize(item) in flat), None)
        matched[group] = found
        if found is None:
            missing.append(group)
    return matched, missing


def load_cases(path: Path) -> list[dict]:
    cases = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise ValueError(f"{path}:{lineno}: expected at least 2 tab-separated fields, got {len(parts)}")
        case_id, wav = parts[0].strip(), parts[1].strip()
        expected = parts[2].strip() if len(parts) > 2 else ""
        cases.append(
            {
                "id": case_id,
                "wav": wav,
                # Whitespace separates required concepts; "a|b" declares
                # equivalent surface forms (e.g. 二十六度|26度 after ITN).
                "expected": [t for t in expected.split() if t],
            }
        )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0, help="only run the first N cases")
    parser.add_argument(
        "--min-hits",
        type=int,
        default=27,
        help="required keyword hits; the Phase A gate for 30 cases is 27",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="do not apply the pass threshold (used for smoke tests / small sets)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("no cases found", file=sys.stderr)
        return 2

    print(f"cases: {len(cases)}")
    recognizer = build_recognizer()

    results = []
    hits = 0
    started = time.perf_counter()
    for case in cases:
        wav_path = Path(case["wav"])
        if not wav_path.is_absolute():
            wav_path = repo_root / wav_path
        if not wav_path.exists():
            results.append({**case, "transcript": None, "error": "wav not found", "hit": False,
                            "missing": case["expected"]})
            print(f"[MISS] {case['id']}: wav not found: {wav_path}")
            continue

        t0 = time.perf_counter()
        stream = recognizer.create_stream()
        stream.accept_waveform(config.SAMPLE_RATE, read_wav(wav_path))
        recognizer.decode_stream(stream)
        elapsed = time.perf_counter() - t0
        transcript = stream.result.text

        matched, missing = match_expected(transcript, case["expected"])
        hit = not missing
        hits += int(hit)
        results.append(
            {
                **case,
                "transcript": transcript,
                "error": None,
                "hit": hit,
                "matched_alternatives": matched,
                "missing": missing,
                "seconds": round(elapsed, 3),
            }
        )
        flag = "HIT " if hit else "MISS"
        print(f"[{flag}] {case['id']} ({elapsed:.2f}s): {transcript}")
        if missing:
            print(f"        missing: {' '.join(missing)}")

    total_seconds = time.perf_counter() - started
    if args.no_gate:
        passed = None
        basis = f"no gate applied (smoke run); hit {hits}/{len(cases)}"
    else:
        passed = hits >= args.min_hits
        basis = f"{len(cases)} cases, >= {args.min_hits} key-information hits"
    summary = {
        "tool": "check_asr.py",
        "cases": len(cases),
        "hits": hits,
        "min_hits": None if args.no_gate else args.min_hits,
        "threshold_basis": basis,
        "passed": passed,
        "total_seconds": round(total_seconds, 2),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    if args.no_gate:
        print(f"hits {hits}/{len(cases)}  (no gate applied)")
    else:
        print(f"hits {hits}/{len(cases)}  threshold {args.min_hits}  -> {'PASS' if passed else 'FAIL'}")
    print(f"wrote {args.out}")
    if args.no_gate:
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
