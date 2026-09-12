"""Measure Phase A CPU voice-model latency and process memory.

Uses bundled model samples so the benchmark is repeatable without microphone
input. It distinguishes initialization, first inference, and hot inference.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import psutil
import soundfile as sf

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import config  # noqa: E402
import voice_models  # noqa: E402


def memory_mb() -> dict:
    info = psutil.Process().memory_info()
    result = {"rss_mb": round(info.rss / 1024**2, 1)}
    if hasattr(info, "peak_wset"):
        result["peak_working_set_mb"] = round(info.peak_wset / 1024**2, 1)
    return result


def timed(fn):
    t0 = time.perf_counter()
    value = fn()
    return value, round(time.perf_counter() - t0, 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    rows = []
    kws, seconds = timed(lambda: voice_models.create_kws(Path("tools/voice-check/cases/wake-keywords.txt")))
    rows.append({"step": "init_kws", "seconds": seconds, **memory_mb()})
    vad, seconds = timed(voice_models.create_vad)
    rows.append({"step": "init_vad", "seconds": seconds, **memory_mb()})
    asr, seconds = timed(voice_models.create_asr)
    rows.append({"step": "init_asr", "seconds": seconds, **memory_mb()})
    tts, seconds = timed(voice_models.create_tts)
    rows.append({"step": "init_tts", "seconds": seconds, **memory_mb()})

    sample = config.models_dir() / config.ASR_DIR / "test_wavs" / "zh.wav"
    audio, sample_rate = sf.read(str(sample), dtype="float32")
    asr_times = []
    transcripts = []
    for _ in range(args.runs):
        text, seconds = timed(lambda: voice_models.transcribe(asr, audio, sample_rate))
        asr_times.append(seconds)
        transcripts.append(text)
        rows.append({"step": "asr", "seconds": seconds, **memory_mb()})

    tts_times = []
    audio_seconds = []
    for _ in range(args.runs):
        result, seconds = timed(lambda: voice_models.synthesize(tts, "已把客厅空调调到二十六度。"))
        samples, sr = result
        tts_times.append(seconds)
        audio_seconds.append(round(len(samples) / sr, 3))
        rows.append({"step": "tts", "seconds": seconds, **memory_mb()})

    # Exercise VAD on the same sample with trailing silence so it returns to false.
    padded = np.concatenate([audio, np.zeros(sample_rate, dtype=np.float32)])
    vad_states = []
    for start in range(0, len(padded) - 511, 512):
        vad_states.append(bool(vad.is_speech(padded[start : start + 512])))

    summary = {
        "tool": "benchmark_voice.py",
        "provider": "cpu",
        "model_root": str(config.models_dir()),
        "runs": args.runs,
        "asr": {
            "cold_seconds": asr_times[0],
            "hot_median_seconds": round(statistics.median(asr_times[1:]), 3) if len(asr_times) > 1 else None,
            "all_seconds": asr_times,
            "transcripts": transcripts,
        },
        "tts": {
            "metric": "full synchronous synthesis time (not first audible output)",
            "full_synthesis_cold_seconds": tts_times[0],
            "full_synthesis_hot_median_seconds": round(statistics.median(tts_times[1:]), 3) if len(tts_times) > 1 else None,
            "all_seconds": tts_times,
            "audio_seconds": audio_seconds,
        },
        "vad": {
            "frames": len(vad_states),
            "speech_frames": sum(vad_states),
            "returned_to_silence": bool(vad_states and not vad_states[-1]),
        },
        "memory": memory_mb(),
        "steps": rows,
        "gpu_expected": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["vad"]["returned_to_silence"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
