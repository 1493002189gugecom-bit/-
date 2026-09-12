"""Read-only audio device inventory for choosing a physical microphone.

Run: python tools/voice-check/list_devices.py
"""
from __future__ import annotations

import json
import sys

import sounddevice as sd

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

RATES = (16000, 24000, 48000, 44100, 8000)


def main() -> int:
    default_in, default_out = sd.default.device
    hostapis = sd.query_hostapis()
    rows = []
    for index, device in enumerate(sd.query_devices()):
        if int(device["max_input_channels"]) <= 0:
            continue
        host = str(hostapis[int(device["hostapi"])]["name"])
        rates = {}
        for rate in RATES:
            try:
                sd.check_input_settings(device=index, channels=1, samplerate=rate, dtype="float32")
                rates[str(rate)] = "ok"
            except sd.PortAudioError:
                rates[str(rate)] = "-"
        rows.append(
            {
                "index": index,
                "hostapi": host,
                "name": str(device["name"]),
                "channels": int(device["max_input_channels"]),
                "native_rate": float(device["default_samplerate"]),
                "is_windows_default": index == default_in,
                "mono_rates": rates,
            }
        )

    print(f"Windows default input index: {default_in}")
    print(f"Windows default output index: {default_out}")
    print()
    print(json.dumps(rows, ensure_ascii=False, indent=1))

    print()
    print("Useful candidates (mono 16 kHz supported):")
    for row in rows:
        if row["mono_rates"].get("16000") == "ok":
            marker = " <- windows default" if row["is_windows_default"] else ""
            print(f"  #{row['index']:>2}  [{row['hostapi']}] {row['name']}{marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
