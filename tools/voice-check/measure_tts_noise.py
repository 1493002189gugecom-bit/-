"""Measure the noise floor of generated TTS audio (not the playback chain).

Reports silence-region RMS, the full-band noise floor, and high-frequency energy
during speech. Distinguishes model artifacts from playback/headset noise.

Run: python tools/voice-check/measure_tts_noise.py
"""
from __future__ import annotations

import argparse
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


def dbfs(value: float) -> float:
    return -np.inf if value <= 0 else 20 * np.log10(value)


def analyse(path: Path) -> dict:
    audio, rate = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.asarray(audio, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0

    # Silence regions: 20 ms frames below 2% of peak are treated as non-speech.
    frame = max(1, int(0.02 * rate))
    frames = [audio[i : i + frame] for i in range(0, len(audio) - frame + 1, frame)]
    threshold = max(peak * 0.02, 1e-5)
    silent = [f for f in frames if float(np.max(np.abs(f))) < threshold]
    silence_rms = (
        float(np.sqrt(np.mean(np.concatenate(silent) ** 2))) if silent else 0.0
    )

    # High-frequency ratio: energy above 6 kHz vs total, during the whole clip.
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio)))) if len(audio) else np.zeros(1)
    freqs = np.fft.rfftfreq(len(audio), 1 / rate) if len(audio) else np.zeros(1)
    total = float(np.sum(spectrum**2)) or 1.0
    high = float(np.sum(spectrum[freqs >= 6000] ** 2))
    return {
        "file": path.name,
        "rate": rate,
        "seconds": round(len(audio) / rate, 2),
        "peak_dbfs": round(dbfs(peak), 1),
        "silence_frames": len(silent),
        "silence_rms_dbfs": round(dbfs(silence_rms), 1) if silence_rms > 0 else -999.0,
        "high_freq_ratio_db": round(10 * np.log10(max(high, 1e-12) / total), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=REPO / "docs/superpowers/reports/artifacts/tts")
    parser.add_argument("--pattern", default="tts-*.wav")
    parser.add_argument("--voice-dir", type=Path, default=REPO / "docs/superpowers/reports/artifacts/tts-voices")
    args = parser.parse_args()

    groups = [("当前 20 条", args.dir / args.pattern)]
    if args.voice_dir.exists():
        groups.append(("音色试听", args.voice_dir / "*.wav"))

    for label, pattern_dir in groups:
        directory = pattern_dir.parent
        pattern = pattern_dir.name
        files = sorted(directory.glob(pattern)) if directory.exists() else []
        if not files:
            print(f"{label}: 无文件")
            continue
        rows = [analyse(p) for p in files]
        silences = [r["silence_rms_dbfs"] for r in rows if r["silence_rms_dbfs"] > -900]
        print(f"=== {label}（{len(rows)} 个文件）===")
        print(f"    峰值中位: {np.median([r['peak_dbfs'] for r in rows]):.1f} dBFS")
        if silences:
            print(f"    静音段底噪中位: {np.median(silences):.1f} dBFS   最差: {max(silences):.1f} dBFS")
            print(f"    静音段数量中位: {np.median([r['silence_frames'] for r in rows]):.0f} 帧")
        print(f"    高频(>6kHz)能量占比中位: {np.median([r['high_freq_ratio_db'] for r in rows]):.1f} dB")
        worst = max(rows, key=lambda r: r["silence_rms_dbfs"])
        print(f"    底噪最大: {worst['file']} ({worst['silence_rms_dbfs']:.1f} dBFS)")
        print()

    print("判读：静音段底噪低于 -60 dBFS 基本不可闻；-50 ~ -40 dBFS 在安静环境可闻；")
    print("      高于 -40 dBFS 属于明显噪声，通常是低比特量化或模型本身的问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
