"""Playback helpers that resample to a verified output target."""
from __future__ import annotations

import time

import numpy as np
import sounddevice as sd

from audio_utils import PlaybackTarget


def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Linear resample; adequate for 16k/24k/48k speech playback."""
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if source_rate == target_rate or len(samples) == 0:
        return samples
    duration = len(samples) / float(source_rate)
    target_count = max(1, int(round(duration * target_rate)))
    source_positions = np.linspace(0.0, len(samples) - 1, num=target_count, dtype=np.float64)
    return np.interp(source_positions, np.arange(len(samples)), samples).astype(np.float32)


def to_channels(samples: np.ndarray, channels: int) -> np.ndarray:
    """Return an interleaved (frames, channels) array."""
    flat = np.asarray(samples, dtype=np.float32).reshape(-1)
    if channels == 1:
        return flat.reshape(-1, 1)
    return np.repeat(flat.reshape(-1, 1), channels, axis=1)


def play(
    samples: np.ndarray,
    source_rate: int,
    target: PlaybackTarget,
    drain_seconds: float = 0.35,
) -> None:
    """Play samples through the verified target, resampling when required."""
    audio = resample(samples, source_rate, target.sample_rate)
    frames = to_channels(audio, target.channels)
    with sd.OutputStream(
        samplerate=target.sample_rate,
        channels=target.channels,
        dtype="float32",
        device=target.index,
    ) as stream:
        stream.write(frames)
        # Let buffered audio reach the device before the stream closes.
        time.sleep(drain_seconds)
