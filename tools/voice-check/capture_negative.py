"""Record the required wake-word negative corpus from the Realtek microphone.

The default is 30 minutes split into six five-minute WAV files. During capture,
play representative conversation/video/music that does not contain either wake
phrase. Recordings stay local and are ignored by git.
"""
from __future__ import annotations

import argparse
import math
import sys
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("tools/voice-check/cases/noise-30min"))
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--chunk-minutes", type=float, default=5.0)
    parser.add_argument("--input-contains", default=config.DEFAULT_INPUT_DEVICE)
    parser.add_argument("--yes", action="store_true", help="skip privacy/recording confirmation")
    args = parser.parse_args()

    if args.minutes <= 0 or args.chunk_minutes <= 0:
        raise ValueError("minutes must be positive")
    device = audio_utils.select_input_device(args.input_contains, config.SAMPLE_RATE)
    chunks = math.ceil(args.minutes / args.chunk_minutes)
    print(f"Input: #{device.index} {device.name} [{device.hostapi}]")
    print(f"将录制约 {args.minutes:g} 分钟，分成 {chunks} 个本地 WAV；请播放不含唤醒词的代表性声音。")
    if not args.yes and input("按 Enter 开始，输入 q 取消：").strip().lower() == "q":
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    remaining = args.minutes * 60
    for index in range(1, chunks + 1):
        seconds = min(args.chunk_minutes * 60, remaining)
        frames = int(seconds * config.SAMPLE_RATE)
        print(f"[{index}/{chunks}] recording {seconds:.1f}s ...")
        audio = sd.rec(
            frames,
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=device.index,
            blocking=True,
        )[:, 0]
        out = args.out_dir / f"negative-{index:02d}.wav"
        sf.write(str(out), audio, config.SAMPLE_RATE, subtype="PCM_16")
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        print(f"saved {out} peak={peak:.4f}")
        remaining -= seconds

    print("录制完成。check_wake.py 会按 WAV 真实时长核验至少 1800 秒。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
