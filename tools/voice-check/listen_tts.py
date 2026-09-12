"""Interactively play and score the 20 generated TTS samples.

Results are persisted after every answer, so the review can be resumed. The
script selects a physical Realtek output explicitly rather than using the
Windows default.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import audio_utils  # noqa: E402
import config  # noqa: E402
import playback  # noqa: E402


def play(wav: Path, target: audio_utils.PlaybackTarget) -> None:
    samples, sample_rate = sf.read(str(wav), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    playback.play(np.asarray(samples, dtype=np.float32), sample_rate, target)


def play_native(wav: Path) -> None:
    """Play through the Windows default endpoint without PortAudio."""
    import winsound

    winsound.PlaySound(str(wav), winsound.SND_FILENAME)


def play_with_fallback(wav: Path, target: audio_utils.PlaybackTarget, mode: str) -> str:
    """Play a WAV, returning the player that was actually used."""
    if mode in ("auto", "portaudio"):
        try:
            play(wav, target)
            return "portaudio"
        except Exception as exc:  # noqa: BLE001
            print(f"    PortAudio 播放失败: {type(exc).__name__}: {exc}")
            if mode == "portaudio":
                raise
    play_native(wav)
    return "winsound"


def listening_gate(results: list[dict], required: int, min_passed: int) -> bool:
    return len(results) == required and sum(1 for row in results if row.get("passed")) >= min_passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation-report", type=Path, default=Path("docs/superpowers/reports/artifacts/tts/tts-report.json"))
    parser.add_argument("--out", type=Path, default=Path("docs/superpowers/reports/artifacts/tts-listening.json"))
    parser.add_argument("--output-contains", default=config.DEFAULT_OUTPUT_DEVICE)
    parser.add_argument("--min-passed", type=int, default=18, help="Phase A listening threshold (default 18/20)")
    parser.add_argument(
        "--player",
        choices=("auto", "portaudio", "winsound"),
        default="auto",
        help="auto falls back to the Windows native player if PortAudio fails",
    )
    args = parser.parse_args()

    generated = json.loads(args.generation_report.read_text(encoding="utf-8"))
    previous = {}
    if args.out.exists():
        previous_doc = json.loads(args.out.read_text(encoding="utf-8"))
        previous = {row["id"]: row for row in previous_doc.get("results", [])}

    output = audio_utils.select_playback_target(args.output_contains)
    print(f"Output: {output.describe()}")
    print("评分：y=清晰可懂；n=不通过；r=重播；q=保存退出")

    results = []
    warned_native = False
    for case in generated["results"]:
        if case["id"] in previous:
            results.append(previous[case["id"]])
            print(f"SKIP 已评分 {case['id']}: {previous[case['id']]['passed']}")
            continue
        wav = Path(case["wav"])
        while True:
            print(f"\n{case['id']}: {case['text']}")
            used = play_with_fallback(wav, output, args.player)
            if used == "winsound" and not warned_native:
                print("    注意：PortAudio 不可用，已改用 Windows 原生播放（走系统默认输出设备）。")
                warned_native = True
            answer = input("是否清晰可懂？[y/n/r/q] ").strip().lower()
            if answer == "r":
                continue
            if answer == "q":
                break
            if answer in {"y", "n"}:
                results.append({"id": case["id"], "text": case["text"], "wav": str(wav), "passed": answer == "y"})
                break
        if answer == "q":
            break
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    passed_count = sum(1 for row in results if row["passed"])
    complete = len(results) == generated["cases"]
    gate_passed = listening_gate(results, generated["cases"], args.min_passed)
    summary = {
        "tool": "listen_tts.py",
        "required": generated["cases"],
        "min_passed": args.min_passed,
        "reviewed": len(results),
        "passed_count": passed_count,
        "complete": complete,
        "passed": gate_passed,
        "results": results,
    }
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"保存到 {args.out}: {passed_count}/{len(results)} 通过；门槛 {args.min_passed}/{generated['cases']}")
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
