"""Audio device selection helpers.

The Windows default input is a virtual NetEase device on this machine. The
voice service therefore selects a physical Realtek microphone by name without
changing the Windows default device. Device indexes are never persisted.
"""
from __future__ import annotations

from dataclasses import dataclass

import sounddevice as sd

import config


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


def _match_candidates(devices: list[AudioDevice], patterns: list[str]) -> list[AudioDevice]:
    """Return devices matching the patterns, preserving the pattern order."""
    ordered: list[AudioDevice] = []
    seen: set[int] = set()
    for pattern in patterns:
        needle = pattern.casefold()
        matched = sorted(
            (d for d in devices if needle in d.name.casefold()),
            key=lambda d: (_HOST_PRIORITY.get(d.hostapi, 99), d.index),
        )
        for device in matched:
            if device.index not in seen:
                seen.add(device.index)
                ordered.append(device)
    return ordered


def _select(
    devices: list[AudioDevice],
    patterns: list[str],
    sample_rate: int,
    check,
    kind: str,
) -> AudioDevice:
    candidates = _match_candidates(devices, patterns)
    errors = []
    for device in candidates:
        try:
            check(
                device=device.index,
                channels=1,
                samplerate=sample_rate,
                dtype="float32",
            )
            return device
        except sd.PortAudioError as exc:
            errors.append(f"{device.index} {device.name} ({device.hostapi}): {exc}")

    available = "\n".join(f"  {d.index}: {d.name} [{d.hostapi}]" for d in devices)
    detail = "\n".join(errors) if errors else "no device matched the preferred names"
    raise RuntimeError(
        f"No usable {kind} for {patterns!r} at {sample_rate} Hz.\n"
        f"Candidate errors:\n{detail}\n\nAvailable {kind} devices:\n{available}\n\n"
        f"Set SMART_HOME_INPUT_DEVICE / SMART_HOME_OUTPUT_DEVICE to override the name list."
    )


def select_input_device(
    name_contains: str | None = None,
    sample_rate: int = 16000,
    patterns: list[str] | None = None,
) -> AudioDevice:
    """Select a physical input device by ordered name preference.

    Matching is case-insensitive. Candidates that cannot open mono float32 at
    the requested sample rate are skipped. This intentionally does not fall
    back to the Windows default input, which may be a virtual or virtualized
    device. Pass a comma-separated list via SMART_HOME_INPUT_DEVICE to adapt
    when a different headset is plugged in.
    """
    if patterns is None:
        patterns = [name_contains] if name_contains else config.input_device_candidates()
    return _select(list_input_devices(), patterns, sample_rate, sd.check_input_settings, "input")


def select_output_device(
    name_contains: str | None = None,
    sample_rate: int = 24000,
    patterns: list[str] | None = None,
) -> AudioDevice:
    """Select a physical output device by ordered name preference."""
    if patterns is None:
        patterns = [name_contains] if name_contains else config.output_device_candidates()
    return _select(list_output_devices(), patterns, sample_rate, sd.check_output_settings, "output")
