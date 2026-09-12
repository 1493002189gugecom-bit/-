"""Measure live input level for candidate devices (records ~2s each, no playback).

Run: python tools/voice-check/probe_levels.py --contains HyperX
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import sounddevice as sd

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SAMPLE_RATE = 16000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contains", action="append", default=None, help="name filter; repeatable")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--top", type=int, default=0, help="0 = only filtered names")
    args = parser.parse_args()

    patterns = [p.casefold() for p in (args.contains or ["HyperX", "Realtek"])]
    hostapis = sd.query_hostapis()
    candidates = []
    for index, device in enumerate(sd.query_devices()):
        if int(device["max_input_channels"]) <= 0:
            continue
        name = str(device["name"])
        if not any(p in name.casefold() for p in patterns):
            continue
        host = str(hostapis[int(device["hostapi"])]["name"])
        try:
            sd.check_input_settings(device=index, channels=1, samplerate=SAMPLE_RATE, dtype="float32")
        except sd.PortAudioError:
            continue
        candidates.append((index, host, name))

    if not candidates:
        print("no matching device supports mono 16 kHz")
        return 2

    print(f"Measuring {len(candidates)} device(s) for {args.seconds:g}s each. Please speak now.")
    best = None
    for index, host, name in candidates:
        try:
            audio = sd.rec(
                int(args.seconds * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=index,
                blocking=True,
            )[:, 0]
        except Exception as exc:  # noqa: BLE001
            print(f"  #{index:>2} [{host}] {name}: ERROR {exc}")
            continue
        audio = np.nan_to_num(audio)
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        verdict = "SIGNAL" if peak > 0.02 else ("very low" if peak > 0.001 else "silent")
        print(f"  #{index:>2} [{host}] {name}: peak={peak:.4f} rms={rms:.5f} -> {verdict}")
        if best is None or peak > best[0]:
            best = (peak, index, host, name)
        time.sleep(0.2)

    if best:
        print()
        print(f"loudest: #{best[1]} [{best[2]}] {best[3]} (peak={best[0]:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
