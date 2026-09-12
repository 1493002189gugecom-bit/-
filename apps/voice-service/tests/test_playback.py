from __future__ import annotations

import numpy as np
import pytest
import sounddevice as sd

import audio_utils
import playback
from audio_utils import AudioDevice, PlaybackTarget


def device(index: int, hostapi: str, name: str = "Headphones (HyperX)", native: float = 48000.0) -> AudioDevice:
    return AudioDevice(
        index=index, name=name, hostapi=hostapi, channels=2, default_samplerate=native
    )


def test_wasapi_preferred_over_directsound_for_playback(monkeypatch):
    # Regression: DirectSound accepted writes but produced no audible output.
    devices = [
        device(18, "Windows DirectSound"),
        device(24, "Windows WASAPI"),
    ]
    monkeypatch.setattr(audio_utils, "list_output_devices", lambda: devices)

    def check(**kwargs):
        if kwargs["device"] == 24:
            # WASAPI rejects mono at the speech rate on this endpoint.
            if kwargs["channels"] == 1 or kwargs["samplerate"] == 24000:
                raise sd.PortAudioError("Invalid number of channels")
        if kwargs["device"] == 18 and kwargs["channels"] != 1:
            raise sd.PortAudioError("only mono")

    monkeypatch.setattr(sd, "check_output_settings", check)
    target = audio_utils.select_playback_target()
    assert target.device.hostapi == "Windows WASAPI"
    assert target.sample_rate == 48000
    assert target.channels == 2


def test_playback_target_falls_back_to_stereo_at_speech_rate(monkeypatch):
    devices = [device(24, "Windows WASAPI")]
    monkeypatch.setattr(audio_utils, "list_output_devices", lambda: devices)

    def check(**kwargs):
        if kwargs["samplerate"] == 24000 and kwargs["channels"] == 1:
            raise sd.PortAudioError("Invalid number of channels")

    monkeypatch.setattr(sd, "check_output_settings", check)
    target = audio_utils.select_playback_target()
    assert (target.sample_rate, target.channels) == (24000, 2)


def test_playback_target_fails_loudly_when_nothing_works(monkeypatch):
    monkeypatch.setattr(audio_utils, "list_output_devices", lambda: [device(18, "Windows DirectSound")])

    def check(**kwargs):
        raise sd.PortAudioError("nope")

    monkeypatch.setattr(sd, "check_output_settings", check)
    with pytest.raises(RuntimeError, match="No usable playback target"):
        audio_utils.select_playback_target()


def test_resample_changes_length_but_keeps_duration():
    source = np.sin(np.linspace(0, 10, 24000, dtype=np.float32)).astype(np.float32)
    out = playback.resample(source, 24000, 48000)
    assert len(out) == 48000
    assert out.dtype == np.float32


def test_resample_at_same_rate_preserves_values_and_does_not_copy():
    source = np.ones(1000, dtype=np.float32)
    out = playback.resample(source, 24000, 24000)
    assert len(out) == len(source)
    assert np.array_equal(out, source)
    assert np.shares_memory(out, source)


def test_to_channels_replicates_mono_for_stereo_output():
    mono = np.array([0.1, -0.2], dtype=np.float32)
    stereo = playback.to_channels(mono, 2)
    assert stereo.shape == (2, 2)
    assert np.allclose(stereo[:, 0], stereo[:, 1])
    assert playback.to_channels(mono, 1).shape == (2, 1)


def test_playback_target_describe_includes_rate_and_channels():
    target = PlaybackTarget(device=device(24, "Windows WASAPI"), sample_rate=48000, channels=2)
    text = target.describe()
    assert "48000" in text and "x2" in text and "WASAPI" in text
