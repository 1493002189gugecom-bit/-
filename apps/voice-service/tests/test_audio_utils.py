from __future__ import annotations

import pytest
import sounddevice as sd

import audio_utils
import config
from audio_utils import AudioDevice


def device(index: int, hostapi: str, name: str = "Realtek microphone") -> AudioDevice:
    return AudioDevice(index=index, name=name, hostapi=hostapi, channels=2, default_samplerate=48000)


def test_select_input_prefers_wasapi(monkeypatch):
    devices = [device(3, "MME"), device(12, "Windows DirectSound"), device(24, "Windows WASAPI")]
    monkeypatch.setattr(audio_utils, "list_input_devices", lambda: devices)
    monkeypatch.setattr(sd, "check_input_settings", lambda **kwargs: None)
    assert audio_utils.select_input_device("Realtek").index == 24


def test_select_input_falls_back_when_wasapi_rejects_rate(monkeypatch):
    devices = [device(12, "Windows DirectSound"), device(24, "Windows WASAPI")]
    monkeypatch.setattr(audio_utils, "list_input_devices", lambda: devices)

    def check(**kwargs):
        if kwargs["device"] == 24:
            raise sd.PortAudioError("Invalid sample rate")

    monkeypatch.setattr(sd, "check_input_settings", check)
    assert audio_utils.select_input_device("Realtek").index == 12


def test_select_input_never_uses_virtual_default(monkeypatch):
    devices = [
        device(1, "MME", "NetEase virtual audio"),
        device(12, "Windows DirectSound", "Realtek microphone"),
    ]
    monkeypatch.setattr(audio_utils, "list_input_devices", lambda: devices)
    monkeypatch.setattr(sd, "check_input_settings", lambda **kwargs: None)
    assert audio_utils.select_input_device("Realtek").index == 12


def test_select_input_fails_loudly_without_matching_device(monkeypatch):
    monkeypatch.setattr(audio_utils, "list_input_devices", lambda: [device(1, "MME", "virtual")])
    with pytest.raises(RuntimeError, match="No usable input"):
        audio_utils.select_input_device("Realtek")


def test_headset_preference_wins_over_onboard_microphone(monkeypatch):
    devices = [
        device(16, "Windows DirectSound", "麦克风阵列 (Realtek(R) Audio)"),
        device(13, "Windows DirectSound", "耳机式麦克风 (HyperX Virtual Surround Sound)"),
    ]
    monkeypatch.setattr(audio_utils, "list_input_devices", lambda: devices)
    monkeypatch.setattr(sd, "check_input_settings", lambda **kwargs: None)
    assert audio_utils.select_input_device().index == 13


def test_onboard_microphone_used_when_headset_is_absent(monkeypatch):
    devices = [device(16, "Windows DirectSound", "麦克风阵列 (Realtek(R) Audio)")]
    monkeypatch.setattr(audio_utils, "list_input_devices", lambda: devices)
    monkeypatch.setattr(sd, "check_input_settings", lambda **kwargs: None)
    assert audio_utils.select_input_device().index == 16


def test_input_device_override_by_environment(monkeypatch):
    monkeypatch.setenv("SMART_HOME_INPUT_DEVICE", "Steam Streaming,HyperX")
    assert config.input_device_candidates() == ["Steam Streaming", "HyperX"]
    devices = [
        device(13, "Windows DirectSound", "耳机式麦克风 (HyperX Virtual Surround Sound)"),
        device(14, "Windows DirectSound", "麦克风 (Steam Streaming Microphone)"),
    ]
    monkeypatch.setattr(audio_utils, "list_input_devices", lambda: devices)
    monkeypatch.setattr(sd, "check_input_settings", lambda **kwargs: None)
    assert audio_utils.select_input_device().index == 14


def test_unusable_headset_falls_back_to_next_preference(monkeypatch):
    devices = [
        device(13, "Windows DirectSound", "耳机式麦克风 (HyperX Virtual Surround Sound)"),
        device(16, "Windows DirectSound", "麦克风阵列 (Realtek(R) Audio)"),
    ]
    monkeypatch.setattr(audio_utils, "list_input_devices", lambda: devices)

    def check(**kwargs):
        if kwargs["device"] == 13:
            raise sd.PortAudioError("Invalid sample rate")

    monkeypatch.setattr(sd, "check_input_settings", check)
    assert audio_utils.select_input_device().index == 16
