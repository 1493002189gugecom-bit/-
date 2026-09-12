"""Audio device selection helpers.

The Windows default input is a virtual NetEase device on this machine. The
voice service therefore selects a physical Realtek microphone by name without
changing the Windows default device. Device indexes are never persisted.
"""
from __future__ import annotations

from dataclasses import dataclass

import sounddevice as sd


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    channels: int
    default_samplerate: float


_HOST_PRIORITY = {
    "Windows WASAPI": 0,
    "Windows DirectSound": 1,
    "MME": 2,
    "Windows WDM-KS": 3,
}


def list_input_devices() -> list[AudioDevice]:
    hostapis = sd.query_hostapis()
    result = []
    for index, raw in enumerate(sd.query_devices()):
        if int(raw["max_input_channels"]) <= 0:
            continue
        host_name = str(hostapis[int(raw["hostapi"])]["name"])
        result.append(
            AudioDevice(
                index=index,
                name=str(raw["name"]),
                hostapi=host_name,
                channels=int(raw["max_input_channels"]),
                default_samplerate=float(raw["default_samplerate"]),
            )
        )
    return result


def list_output_devices() -> list[AudioDevice]:
    hostapis = sd.query_hostapis()
    result = []
    for index, raw in enumerate(sd.query_devices()):
        if int(raw["max_output_channels"]) <= 0:
            continue
        host_name = str(hostapis[int(raw["hostapi"])]["name"])
        result.append(
            AudioDevice(
                index=index,
                name=str(raw["name"]),
                hostapi=host_name,
                channels=int(raw["max_output_channels"]),
                default_samplerate=float(raw["default_samplerate"]),
            )
        )
    return result


def select_output_device(name_contains: str = "Realtek", sample_rate: int = 24000) -> AudioDevice:
    """Select a physical output by name, preferring WASAPI."""
    needle = name_contains.casefold()
    candidates = [d for d in list_output_devices() if needle in d.name.casefold()]
    candidates.sort(key=lambda d: (_HOST_PRIORITY.get(d.hostapi, 99), d.index))
    errors = []
    for device in candidates:
        try:
            sd.check_output_settings(
                device=device.index,
                channels=1,
                samplerate=sample_rate,
                dtype="float32",
            )
            return device
        except sd.PortAudioError as exc:
            errors.append(f"{device.index} {device.name} ({device.hostapi}): {exc}")
    detail = "\n".join(errors) if errors else "no matching physical output"
    raise RuntimeError(
        f"No usable output containing {name_contains!r} at {sample_rate} Hz.\n{detail}"
    )


def select_input_device(name_contains: str = "Realtek", sample_rate: int = 16000) -> AudioDevice:
    """Select a physical input device by name, preferring WASAPI.

    Matching is case-insensitive. Candidates that cannot open mono float32 at
    the requested sample rate are skipped. This intentionally does not fall
    back to the Windows default input because that is a virtual device here.
    """
    needle = name_contains.casefold()
    candidates = [d for d in list_input_devices() if needle in d.name.casefold()]
    candidates.sort(key=lambda d: (_HOST_PRIORITY.get(d.hostapi, 99), d.index))

    errors = []
    for device in candidates:
        try:
            sd.check_input_settings(
                device=device.index,
                channels=1,
                samplerate=sample_rate,
                dtype="float32",
            )
            return device
        except sd.PortAudioError as exc:
            errors.append(f"{device.index} {device.name} ({device.hostapi}): {exc}")

    available = "\n".join(
        f"  {d.index}: {d.name} [{d.hostapi}]" for d in list_input_devices()
    )
    detail = "\n".join(errors) if errors else "no matching physical input"
    raise RuntimeError(
        f"No usable input containing {name_contains!r} at {sample_rate} Hz.\n"
        f"Candidate errors:\n{detail}\nAvailable inputs:\n{available}"
    )
