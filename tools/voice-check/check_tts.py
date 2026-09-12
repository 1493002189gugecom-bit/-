"""Offline TTS check: synthesize home-announcement sentences to WAV files.

Phase A6. Reads a TSV of cases (id, text) and synthesizes each with the
configured TTS provider (Edge neural voices by default) into WAV files for human
listening. This script does not judge audio quality; the operator records
pass/fail per case in the report.

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

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import config  # noqa: E402
import voice_models  # noqa: E402


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
    parser.add_argument("--provider", default=None, help="edge (default) or kokoro")
    parser.add_argument("--voice", default=None, help="edge voice name, e.g. zh-CN-XiaoxiaoNeural")
    parser.add_argument("--report", type=Path, default=None, help="where to write JSON metadata")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if not cases:
        print("no cases found", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    engine = voice_models.create_tts(args.provider, args.voice)
    print(f"cases: {len(cases)}  provider: {engine.provider}  voice: {engine.voice}")

    results = []
    for case in cases:
        out = args.out_dir / f"{case['id']}.wav"
        t0 = time.perf_counter()
        try:
            samples, rate = engine.render_to(case["text"], out)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - t0
            print(f"[FAIL] {case['id']}: {type(exc).__name__}: {exc}")
            results.append(
                {
                    **case,
                    "wav": None,
                    "seconds": round(elapsed, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        elapsed = time.perf_counter() - t0
        duration = len(samples) / rate
        print(f"[OK  ] {case['id']} ({elapsed:.2f}s, {duration:.2f}s audio): {case['text']}")
        results.append(
            {
                **case,
                "wav": str(out),
                "seconds": round(elapsed, 3),
                "audio_seconds": round(duration, 3),
                "sample_rate": rate,
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
                "provider": engine.provider,
                "voice": engine.voice,
                "cases": len(cases),
                "generated": generated_count,
                "passed": generation_passed,
                "note": (
                    "generation must succeed for every case; announcements are network-backed, "
                    "so a failure is reported rather than substituted locally; "
                    "listening requires >=18/20 and is recorded separately"
                ),
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
