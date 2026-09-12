"""Shared configuration for the voice service and offline check tools.

Model files are never committed. They live outside the repository by default,
on the D drive as requested for this machine, and can be overridden with the
SMART_HOME_MODELS_DIR environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODELS_DIR = Path(r"D:\smart-home-models")


def models_dir() -> Path:
    """Return the model root directory (env override wins)."""
    raw = os.environ.get("SMART_HOME_MODELS_DIR")
    return Path(raw) if raw else DEFAULT_MODELS_DIR


# Directory names inside the model root, matching the extracted tarballs.
ASR_DIR = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
ASR_MODEL = "model.int8.onnx"
ASR_TOKENS = "tokens.txt"

TTS_DIR = "kokoro-int8-multi-lang-v1_1"
TTS_MODEL = "model.int8.onnx"
TTS_VOICES = "voices.bin"
TTS_TOKENS = "tokens.txt"
TTS_DATA_DIR = "espeak-ng-data"
TTS_LEXICON = "lexicon-us-en.txt,lexicon-zh.txt"
TTS_DICT_DIR = "dict"

KWS_DIR = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
KWS_CHUNK16 = True  # chunk-16 => ~320 ms latency, higher accuracy
KWS_TOKEN_TYPE = "phone+ppinyin"
KWS_LEXICON = "en.phone"

VAD_MODEL = "silero_vad.onnx"

# The default input device on this machine is a virtual device, so the physical
# Realtek microphone is selected explicitly. Device names are matched as
# substrings of the PortAudio name.
DEFAULT_INPUT_DEVICE = "Realtek"
DEFAULT_OUTPUT_DEVICE = "Realtek"

WAKE_WORD_CANDIDATES = ("小屋小屋", "你好小屋")
SAMPLE_RATE = 16000


def require(path: Path) -> Path:
    """Fail loudly with an actionable message when a model path is missing."""
    if not path.exists():
        raise FileNotFoundError(
            f"missing model artifact: {path}\n"
            f"model root = {models_dir()} (override with SMART_HOME_MODELS_DIR)"
        )
    return path


def asr_paths() -> dict:
    root = models_dir() / ASR_DIR
    return {
        "model": require(root / ASR_MODEL),
        "tokens": require(root / ASR_TOKENS),
    }


def tts_paths() -> dict:
    root = models_dir() / TTS_DIR
    return {
        "model": require(root / TTS_MODEL),
        "voices": require(root / TTS_VOICES),
        "tokens": require(root / TTS_TOKENS),
        "data_dir": require(root / TTS_DATA_DIR),
        "lexicon": ",".join(str(root / n) for n in TTS_LEXICON.split(",")),
        "dict_dir": root / TTS_DICT_DIR,
    }


def kws_paths() -> dict:
    root = models_dir() / KWS_DIR
    suffix = "chunk-16" if KWS_CHUNK16 else "chunk-8"
    return {
        "encoder": require(root / f"encoder-epoch-13-avg-2-{suffix}-left-64.int8.onnx"),
        "decoder": require(root / f"decoder-epoch-13-avg-2-{suffix}-left-64.onnx"),
        "joiner": require(root / f"joiner-epoch-13-avg-2-{suffix}-left-64.int8.onnx"),
        "tokens": require(root / "tokens.txt"),
        "lexicon": require(root / KWS_LEXICON),
    }


def vad_model() -> Path:
    return require(models_dir() / VAD_MODEL)
