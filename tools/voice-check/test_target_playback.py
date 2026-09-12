"""Play a tone through the selected playback target and confirm audibility.

Run: python tools/voice-check/test_target_playback.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import audio_utils  # noqa: E402
import playback  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--freq", type=float, default=440.0)
    parser.add_argument("--volume", type=float, default=0.35)
    parser.add_argument("--loop", type=int, default=3)
    args = parser.parse_args()

    target = audio_utils.select_playback_target()
    print(f"播放目标: {target.describe()}")
    print("（若之前只有 winsound 能出声，现在应当也能听到）")

    t = np.arange(int(args.seconds * 24000), dtype=np.float32) / 24000
    tone = (args.volume * np.sin(2 * np.pi * args.freq * t)).astype(np.float32)
    fade = int(0.05 * 24000)
    tone[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    tone[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)

    for attempt in range(1, args.loop + 1):
        print(f"[{attempt}/{args.loop}] 播放 {args.freq:g} Hz ……")
        playback.play(tone, 24000, target)
        time.sleep(0.8)

    print()
    print("听到了吗？如果刚才的 1/3 里只有 3 没听到，而这次听到了，说明修复有效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
