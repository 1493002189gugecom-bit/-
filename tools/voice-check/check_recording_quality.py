"""Summarize recorded corpus loudness and duration before scoring it.

Run: python tools/voice-check/check_recording_quality.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parents[2]
GROUPS = {
    "ASR 30 条": REPO / "tools/voice-check/cases/audio",
    "唤醒 小屋小屋": REPO / "tools/voice-check/cases/audio/wake/xiaowu-xiaowu",
    "唤醒 你好小屋": REPO / "tools/voice-check/cases/audio/wake/nihao-xiaowu",
    "负例 30 分钟": REPO / "tools/voice-check/cases/noise-30min",
    "声学回环": REPO / "tools/voice-check/cases/self-trigger",
}

# peak >= 0.1 is comfortably usable; below 0.02 means no real signal.
GOOD_PEAK = 0.1
SILENT_PEAK = 0.02


def main() -> int:
    for label, directory in GROUPS.items():
        if not directory.exists():
            print(f"{label}: 目录不存在")
            continue
        pattern = "asr-*.wav" if directory == GROUPS["ASR 30 条"] else "*.wav"
        files = sorted(p for p in directory.rglob(pattern) if p.is_file())
        if not files:
            print(f"{label}: 0 个文件")
            continue

        peaks, durations, rates = [], [], set()
        for path in files:
            audio, rate = sf.read(str(path), dtype="float32", always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            peaks.append(float(np.max(np.abs(audio))) if len(audio) else 0.0)
            durations.append(len(audio) / rate if rate else 0.0)
            rates.add(rate)

        low = [p.name for p, peak in zip(files, peaks) if peak < GOOD_PEAK]
        silent = [p.name for p, peak in zip(files, peaks) if peak < SILENT_PEAK]
        print(f"{label}: {len(files)} 个文件，采样率 {sorted(rates)}")
        print(
            f"    peak 中位={np.median(peaks):.4f} 最小={min(peaks):.4f} 最大={max(peaks):.4f}"
            f"  时长 {min(durations):.2f}-{max(durations):.2f}s 合计 {sum(durations):.1f}s"
        )
        if silent:
            print(f"    [严重] 几乎无声 {len(silent)} 个: {silent[:5]}")
        elif low:
            print(f"    [偏小] peak < {GOOD_PEAK} 的 {len(low)} 个: {low[:5]}")
        else:
            print("    [良好] 全部 peak >= 0.1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
