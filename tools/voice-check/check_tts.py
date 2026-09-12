"""Offline TTS check: synthesize home-announcement sentences to WAV files.

Phase A6. Reads a TSV of cases (id, text), synthesizes each with Kokoro via
sherpa-onnx on CPU, and writes WAV files for human listening. This script does
not judge audio quality; the operator records pass/fail per case in the report.

Usage:
    python check_tts.py --cases tools/voice-check/cases/tts-20.tsv \
        --out-dir docs/superpowers/reports/artifacts/tts
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import sherpa_onnx

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import config  # noqa: E402

# Kokoro Chinese voice ids: 45-48 female (zf_*), 49-52 male (zm_*).
DEFAULT_SPEAKER_ID = 47  # zf_xiaoxiao


def build_tts(speaker_id: int) -> sherpa_onnx.OfflineTts:
    paths = config.tts_paths()
    tts_config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(paths["model"]),
                voices=str(paths["voices"]),
                tokens=str(paths["tokens"]),
                data_dir=str(paths["data_dir"]),
                lexicon=paths["lexicon"],
            ),
            num_threads=2,
            provider="cpu",
            debug=False,
        ),
        max_num_sentences=1,
    )
    if not tts_config.validate():
        raise RuntimeError("invalid TTS config; check model paths and lexicon")
    return sherpa_onnx.OfflineTts(tts_config)


def load_cases(path: Path) -> list[dict]:
    cases = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise ValueError(f"{path}:{lineno}: expected 'id<TAB>text'")
        cases.append({"id": parts[0].strip(), "text": parts[1].strip()})
    return cases


def generation_complete(results: list[dict], case_count: int) -> bool:
    return len(results) == case_count and all(row.get("wav") and not row.get("error") for row in results)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--speaker-id", type=int, default=DEFAULT_SPEAKER_ID)
    parser.add_argument("--report", type=Path, default=None, help="where to write JSON metadata")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if not cases:
        print("no cases found", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"cases: {len(cases)}  speaker_id: {args.speaker_id}")
    tts = build_tts(args.speaker_id)
    print(f"tts sample_rate: {tts.sample_rate}")

    import soundfile as sf

    results = []
    for case in cases:
        t0 = time.perf_counter()
        audio = tts.generate(case["text"], sid=args.speaker_id, speed=1.0)
        elapsed = time.perf_counter() - t0
        if audio is None or len(audio.samples) == 0:
            print(f"[FAIL] {case['id']}: no audio generated")
            results.append({**case, "wav": None, "seconds": round(elapsed, 3), "error": "no audio"})
            continue
        out = args.out_dir / f"{case['id']}.wav"
        samples = np.asarray(audio.samples, dtype=np.float32)
        sf.write(str(out), samples, audio.sample_rate, subtype="PCM_16")
        duration = len(samples) / audio.sample_rate
        print(f"[OK  ] {case['id']} ({elapsed:.2f}s, {duration:.2f}s audio): {case['text']}")
        results.append(
            {
                **case,
                "wav": str(out),
                "seconds": round(elapsed, 3),
                "audio_seconds": round(duration, 3),
                "error": None,
            }
        )

    report_path = args.report or (args.out_dir / "tts-report.json")
    generated_count = sum(1 for r in results if r.get("wav"))
    generation_passed = generation_complete(results, len(cases))
    report_path.write_text(
        json.dumps(
            {
                "tool": "check_tts.py",
                "speaker_id": args.speaker_id,
                "cases": len(cases),
                "generated": generated_count,
                "passed": generation_passed,
                "note": "generation must succeed for every case; listening requires >=18/20 and is recorded separately",
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {report_path}  generated={generated_count}/{len(cases)}")
    return 0 if generation_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
