"""Diagnose microphone loudness for the configured input preference.

Records each candidate device for a few seconds, writes WAV files so they can
be played back, and reports dBFS plus a short time-series so low gain can be
distinguished from true silence.

Run: python tools/voice-check/diagnose_mic.py --seconds 5
"""
from __future__ import annotations

import argparse
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
import config  # noqa: E402

SAMPLE_RATE = 16000


def dbfs(value: float) -> str:
    if value <= 0:
        return "-inf"
    return f"{20 * np.log10(value):.1f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--out-dir", type=Path, default=Path("tools/voice-check/cases/audio/mic-diag"))
    parser.add_argument("--candidates", default=None, help="override comma-separated name list")
    parser.add_argument("--countdown", type=int, default=8, help="seconds before the first capture")
    parser.add_argument("--channels", type=int, default=1)
    args = parser.parse_args()

    patterns = (
        [p.strip() for p in args.candidates.split(",") if p.strip()]
        if args.candidates
        else ["HyperX", "Realtek"]
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)

    hostapis = sd.query_hostapis()
    candidates = []
    for index, device in enumerate(sd.query_devices()):
        if int(device["max_input_channels"]) <= 0:
            continue
        name = str(device["name"])
        if not any(p.casefold() in name.casefold() for p in patterns):
            continue
        host = str(hostapis[int(device["hostapi"])]["name"])
        try:
            sd.check_input_settings(
                device=index, channels=args.channels, samplerate=SAMPLE_RATE, dtype="float32"
            )
        except sd.PortAudioError:
            continue
        candidates.append((index, host, name))

    if not candidates:
        print("no matching usable input device")
        return 2

    print(f"将依次测试 {len(candidates)} 个设备，每个 {args.seconds:g} 秒。")
    print("请先确认耳机上的静音键已解除，然后用正常到稍大的音量持续数数。")
    for remaining in range(args.countdown, 0, -1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1)

    results = []
    for index, host, name in candidates:
        print(f"\n>>> 现在开始录 #{index} [{host}] {name} —— 请立刻大声数数！")
        captured = sd.rec(
            int(args.seconds * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=args.channels,
            dtype="float32",
            device=index,
            blocking=True,
        )
        captured = np.nan_to_num(np.asarray(captured, dtype=np.float32))
        if captured.ndim > 1:
            per_channel = [captured[:, ch] for ch in range(captured.shape[1])]
            print(
                "    每通道峰值: "
                + ", ".join(f"ch{ch}={float(np.max(np.abs(c))):.4f}" for ch, c in enumerate(per_channel))
            )
            audio = per_channel[0]
        else:
            audio = captured
        out = args.out_dir / f"diag-{index:02d}.wav"
        sf.write(str(out), audio, SAMPLE_RATE, subtype="PCM_16")

        if len(audio):
            peak = float(np.max(np.abs(audio)))
            rms = float(np.sqrt(np.mean(np.square(audio))))
            # 10 buckets show whether energy is present across the whole window.
            chunks = np.array_split(audio, 10)
            series = " ".join(f"{dbfs(float(np.sqrt(np.mean(np.square(c))))):>6}" for c in chunks if len(c))
        else:
            peak = rms = 0.0
            series = "(no samples)"

        verdict = (
            "GOOD (usable)"
            if peak >= 0.1
            else "LOW (needs higher mic volume)"
            if peak >= 0.01
            else "VERY LOW / SILENT (check mute, gain, or wrong jack)"
        )
        print(f"    peak={peak:.4f} ({dbfs(peak)} dBFS)  rms={rms:.5f} ({dbfs(rms)} dBFS)  -> {verdict}")
        print(f"    per-0.5s RMS dBFS: {series}")
        print(f"    saved: {out}")
        results.append((peak, index, host, name))

    print("\n=== 结论 ===")
    for peak, index, host, name in sorted(results, reverse=True):
        print(f"  {dbfs(peak):>6} dBFS  #{index:>2} [{host}] {name}")
    print()
    print("判读参考：峰值 >= -20 dBFS 良好；-40~-20 dBFS 偏小但可用；< -40 dBFS 需要提高麦克风音量或关闭静音。")
    print("回放刚才的 WAV 可以直接确认有没有录到你的声音。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
