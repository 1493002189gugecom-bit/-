from __future__ import annotations

from pathlib import Path

import pytest

import config


def test_default_model_root_is_d_drive(monkeypatch):
    monkeypatch.delenv("SMART_HOME_MODELS_DIR", raising=False)
    assert config.models_dir() == Path(r"D:\smart-home-models")


def test_model_root_environment_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SMART_HOME_MODELS_DIR", str(tmp_path))
    assert config.models_dir() == tmp_path


def test_require_reports_model_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SMART_HOME_MODELS_DIR", str(tmp_path))
    missing = tmp_path / "missing.onnx"
    with pytest.raises(FileNotFoundError) as exc:
        config.require(missing)
    assert str(missing) in str(exc.value)
    assert "SMART_HOME_MODELS_DIR" in str(exc.value)


@pytest.mark.skipif(not config.DEFAULT_MODELS_DIR.exists(), reason="local model directory is not installed")
def test_downloaded_model_paths_exist(monkeypatch):
    monkeypatch.delenv("SMART_HOME_MODELS_DIR", raising=False)
    assert all(path.exists() for path in config.asr_paths().values())
    assert all(path.exists() for key, path in config.tts_paths().items() if key != "lexicon")
    assert all(path.exists() for path in config.kws_paths().values())
    assert config.vad_model().exists()
