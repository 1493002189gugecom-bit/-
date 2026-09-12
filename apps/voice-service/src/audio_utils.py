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


@dataclass(frozen=True)
class PlaybackTarget:
    """A concrete, verified way to play audio on one device."""

    device: AudioDevice
    sample_rate: int
    channels: int

    @property
    def index(self) -> int:
        return self.device.index

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def hostapi(self) -> str:
        return self.device.hostapi

    def describe(self) -> str:
        return (
            f"#{self.device.index} {self.device.name} [{self.device.hostapi}] "
            f"{self.sample_rate} Hz x{self.channels}"
        )


# WASAPI is the modern path straight to the hardware endpoint and is preferred
# for playback. Legacy MME and DirectSound are ordered next for input, where
# WDM-KS is avoided: PortAudio reports "Blocking API not supported yet" for
# WDM-KS streams, which is fragile for the capture loop.
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


def select_playback_target(
    name_contains: str | None = None,
    sample_rate: int = config.TTS_SAMPLE_RATE,
    patterns: list[str] | None = None,
) -> PlaybackTarget:
    """Select an output device *and* a verified channel/rate combination.

    Some virtual-surround endpoints reject mono or the 24 kHz speech rate on
    WASAPI, so stereo and the device-native rate are tried as well. Returning the
    working combination avoids the failure mode where a legacy host API accepts
    writes but produces no audible output.
    """
    if patterns is None:
        patterns = [name_contains] if name_contains else config.output_device_candidates()

    devices = list_output_devices()
    candidates = _match_candidates(devices, patterns)
    errors: list[str] = []

    for device in candidates:
        attempts: list[tuple[int, int]] = [
            (sample_rate, 1),
            (sample_rate, 2),
            (int(device.default_samplerate), 2),
            (config.OUTPUT_FALLBACK_SAMPLE_RATE, 2),
            (44100, 2),
        ]
        seen: set[tuple[int, int]] = set()
        for rate, channels in attempts:
            if rate <= 0 or (rate, channels) in seen:
                continue
            seen.add((rate, channels))
            try:
                sd.check_output_settings(
                    device=device.index,
                    channels=channels,
                    samplerate=rate,
                    dtype="float32",
                )
                return PlaybackTarget(device=device, sample_rate=rate, channels=channels)
            except sd.PortAudioError as exc:
                errors.append(
                    f"{device.index} {device.name} ({device.hostapi}) {rate}Hz x{channels}: {exc}"
                )

    available = "\n".join(f"  {d.index}: {d.name} [{d.hostapi}]" for d in devices)
    detail = "\n".join(errors) if errors else "no device matched the preferred names"
    raise RuntimeError(
        f"No usable playback target for {patterns!r}.\n"
        f"Attempts:\n{detail}\n\nAvailable output devices:\n{available}"
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
