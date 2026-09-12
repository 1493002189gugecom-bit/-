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
    """The Edge path is stubbed with a real MP3 payload to avoid network tests."""
    mp3 = _make_mp3_bytes()
    monkeypatch.setattr(voice_models, "_edge_synthesize", lambda text, voice: _decode(mp3))
    engine = voice_models.TtsEngine(provider="edge")
    out = tmp_path / "case.wav"
    samples, rate = engine.render_to("测试文本", out)
    assert out.exists()
    written, written_rate = sf.read(str(out), dtype="float32")
    assert written_rate == rate
    assert len(written) == len(samples)


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


def _make_mp3_bytes() -> bytes:
    """Return a tiny real MP3 produced by edge-tts if one is cached, else skip."""
    cached = REPO / "docs/superpowers/reports/artifacts/tts-compare/_probe.mp3"
    if cached.exists():
        data = cached.read_bytes()
        if data:
            return data
    pytest.skip("no cached edge-tts MP3 available for the stub")


def _decode(payload: bytes) -> tuple[np.ndarray, int]:
    import io

    samples, rate = sf.read(io.BytesIO(payload), dtype="float32", always_2d=False)
    return np.asarray(samples, dtype=np.float32), int(rate)
