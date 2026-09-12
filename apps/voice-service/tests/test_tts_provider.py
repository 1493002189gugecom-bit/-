from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import config
import voice_models

REPO = Path(__file__).resolve().parents[3]


def test_default_provider_is_edge():
    assert config.tts_provider() == "edge"
    assert config.edge_voice() == "zh-CN-XiaoxiaoNeural"


def test_provider_and_voice_can_be_overridden(monkeypatch):
    monkeypatch.setenv("SMART_HOME_TTS_PROVIDER", "KOKORO")
    monkeypatch.setenv("SMART_HOME_TTS_VOICE", "zh-CN-YunyangNeural")
    assert config.tts_provider() == "kokoro"
    assert config.edge_voice() == "zh-CN-YunyangNeural"


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="unknown TTS provider"):
        voice_models.TtsEngine(provider="nonsense")


def test_edge_candidate_voices_are_chinese():
    assert config.EDGE_VOICE_CANDIDATES
    assert all(v.startswith("zh-CN-") for v in config.EDGE_VOICE_CANDIDATES)


def test_render_to_writes_a_playable_wav(tmp_path, monkeypatch):
    """The Edge fetch is stubbed with decoded audio so no network is used."""
    monkeypatch.setattr(voice_models, "_edge_synthesize", lambda text, voice: _stub_audio())
    engine = voice_models.TtsEngine(provider="edge")
    out = tmp_path / "case.wav"
    samples, rate = engine.render_to("测试文本", out)
    assert out.exists()
    written, written_rate = sf.read(str(out), dtype="float32")
    assert written_rate == rate
    assert len(written) == len(samples)


def test_edge_audio_is_decoded_and_averaged_to_mono(tmp_path):
    """The real decoder must downmix stereo payloads to mono."""
    stereo = np.stack([_tone(), _tone() * 0.5], axis=1)
    payload = _encode_wav(stereo)
    samples, rate = voice_models._decode_edge_audio(payload)
    assert samples.ndim == 1
    assert rate == 24000
    assert len(samples) == len(stereo)


def test_edge_decoder_rejects_empty_payload():
    with pytest.raises(Exception):
        voice_models._decode_edge_audio(b"")


def test_edge_failure_is_not_substituted_locally(monkeypatch):
    def boom(text, voice):
        raise RuntimeError("edge-tts failed after 3 attempts: network down")

    monkeypatch.setattr(voice_models, "_edge_synthesize", boom)
    engine = voice_models.TtsEngine(provider="edge")
    with pytest.raises(RuntimeError, match="network down"):
        engine.synthesize("测试")


def test_speaker_id_arguments_rejected_for_edge():
    engine = voice_models.TtsEngine(provider="edge")
    with pytest.raises(ValueError, match="only apply to the kokoro provider"):
        voice_models.synthesize(engine, "测试", speaker_id=47)


def test_edge_retries_are_bounded(monkeypatch):
    """A failing fetch must give up rather than hang forever."""
    attempts = {"count": 0}

    async def fake_stream(self):  # pragma: no cover - replaced below
        raise AssertionError("unused")

    monkeypatch.setattr(config, "EDGE_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(config, "EDGE_RETRY_DELAY_SECONDS", 0.0)

    import edge_tts

    class FakeCommunicate:
        def __init__(self, *args, **kwargs):
            attempts["count"] += 1

        async def stream(self):
            raise RuntimeError("network down")
            yield  # pragma: no cover

    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate, raising=False)
    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        voice_models._edge_synthesize("测试", "zh-CN-XiaoxiaoNeural")
    assert attempts["count"] == 2
    del fake_stream


def _tone(seconds: float = 0.25, rate: int = 24000) -> np.ndarray:
    t = np.arange(int(seconds * rate), dtype=np.float32) / rate
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def _stub_audio() -> tuple[np.ndarray, int]:
    return _tone(), 24000


def _encode_wav(samples: np.ndarray, rate: int = 24000) -> bytes:
    import io

    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
