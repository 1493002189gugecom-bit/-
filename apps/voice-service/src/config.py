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

# Playback sample rate for generated speech (Kokoro emits 24 kHz).
TTS_SAMPLE_RATE = 24000
# Virtual surround endpoints often expose only 48 kHz; resample when needed.
OUTPUT_FALLBACK_SAMPLE_RATE = 48000

# The Windows default input on this machine was a virtual NetEase device, so a
# physical device is selected explicitly by name instead. Device names change
# when headsets are plugged in, so this is an ordered preference list: the first
# candidate that opens as mono float32 at the required rate wins. Override the
# whole list with SMART_HOME_INPUT_DEVICE (comma-separated substrings).
DEFAULT_INPUT_DEVICE_CANDIDATES = (
    "HyperX",
    "Realtek",
)
DEFAULT_OUTPUT_DEVICE_CANDIDATES = (
    "HyperX",
    "Realtek",
)


def input_device_candidates() -> list[str]:
    """Return ordered name substrings used to pick the physical microphone."""
    raw = os.environ.get("SMART_HOME_INPUT_DEVICE")
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return list(DEFAULT_INPUT_DEVICE_CANDIDATES)


def output_device_candidates() -> list[str]:
    raw = os.environ.get("SMART_HOME_OUTPUT_DEVICE")
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return list(DEFAULT_OUTPUT_DEVICE_CANDIDATES)


# Kept for backwards compatibility with earlier scripts/README wording.
DEFAULT_INPUT_DEVICE = DEFAULT_INPUT_DEVICE_CANDIDATES[0]
DEFAULT_OUTPUT_DEVICE = DEFAULT_OUTPUT_DEVICE_CANDIDATES[0]

WAKE_WORD_CANDIDATES = ("小屋小屋", "你好小屋")
SAMPLE_RATE = 16000


# Kokoro v1.1 Chinese voices: 45-48 female (zf_*), 49-52 male (zm_*).
# Audition them with tools/voice-check/audition_voices.py, then set
# SMART_HOME_TTS_SPEAKER to the chosen id.
DEFAULT_TTS_SPEAKER_ID = 47
DEFAULT_TTS_SPEED = 1.0


def tts_speaker_id() -> int:
    """Return the configured Kokoro speaker id."""
    raw = os.environ.get("SMART_HOME_TTS_SPEAKER")
    if raw and raw.strip().isdigit():
        return int(raw.strip())
    return DEFAULT_TTS_SPEAKER_ID


def tts_speed() -> float:
    """Return the configured speech rate."""
    raw = os.environ.get("SMART_HOME_TTS_SPEED")
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return DEFAULT_TTS_SPEED
        if 0.5 <= value <= 2.0:
            return value
    return DEFAULT_TTS_SPEED


# Text-to-speech. Edge neural voices are used for announcements because they are
# far more natural than the local 82M Kokoro model. This requires network access:
# when it fails the announcement is reported as failed rather than silently
# substituted.
TTS_PROVIDER = "edge"
EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
EDGE_VOICE_CANDIDATES = (
    "zh-CN-XiaoxiaoNeural",  # female, warm
    "zh-CN-XiaoyiNeural",  # female, lively
    "zh-CN-YunxiNeural",  # male, lively
    "zh-CN-YunyangNeural",  # male, professional
    "zh-CN-YunjianNeural",  # male, passionate
)
EDGE_RATE = "+0%"
EDGE_VOLUME = "+0%"
EDGE_PITCH = "+0Hz"
EDGE_TIMEOUT_SECONDS = 30.0
# Online synthesis needs retries: transient network hiccups otherwise surface as
# announcement failures. A slow request is retried rather than accepted.
EDGE_MAX_ATTEMPTS = 3
EDGE_RETRY_DELAY_SECONDS = 1.5
EDGE_SLOW_SECONDS = 6.0
# Fallback sample rate used only if the returned MP3 reports no rate.
TTS_FALLBACK_SAMPLE_RATE = 24000


def tts_provider() -> str:
    return os.environ.get("SMART_HOME_TTS_PROVIDER", TTS_PROVIDER).strip().lower()


def edge_voice() -> str:
    return os.environ.get("SMART_HOME_TTS_VOICE", EDGE_VOICE).strip()


def edge_rate() -> str:
    return os.environ.get("SMART_HOME_TTS_RATE", EDGE_RATE).strip()


def edge_volume() -> str:
    return os.environ.get("SMART_HOME_TTS_VOLUME", EDGE_VOLUME).strip()


def edge_pitch() -> str:
    return os.environ.get("SMART_HOME_TTS_PITCH", EDGE_PITCH).strip()


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


# ---------------------------------------------------------------- voice agent
# The agent's LLM key lives in a local git-ignored file (or the environment).
# It is never written to logs, exceptions, the repository, or a command line.
DEFAULT_AGENT_ENV_FILE = Path("runtime/voice-agent/agent.env")
DEFAULT_AGENT_BASE_URL = "https://api.deepseek.com"
DEFAULT_AGENT_MODEL = "deepseek-chat"
DEFAULT_AGENT_TIMEOUT_SECONDS = 20.0
DEFAULT_AGENT_DEADLINE_SECONDS = 20.0
DEFAULT_AGENT_MAX_TOOL_ROUNDS = 4
DEFAULT_HOME_SERVICE_URL = "http://127.0.0.1:8765"
FIXED_REPLY_TEXT = "收到。"


def agent_env_file() -> Path:
    raw = os.environ.get("SMART_HOME_AGENT_ENV_FILE")
    return Path(raw) if raw else DEFAULT_AGENT_ENV_FILE


def agent_api_key() -> str:
    """Return the LLM key from the environment, else from the local env file."""
    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if value:
        return value
    path = agent_env_file()
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, raw = line.partition("=")
        if separator and key.strip() == "DEEPSEEK_API_KEY":
            return raw.strip().strip("\"'")
    return ""


def agent_enabled() -> bool:
    raw = os.environ.get("SMART_HOME_AGENT", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def agent_base_url() -> str:
    return os.environ.get("SMART_HOME_AGENT_BASE_URL", DEFAULT_AGENT_BASE_URL).strip()


def agent_model() -> str:
    return os.environ.get("SMART_HOME_AGENT_MODEL", DEFAULT_AGENT_MODEL).strip()


def agent_timeout_seconds() -> float:
    return _positive_float("SMART_HOME_AGENT_TIMEOUT", DEFAULT_AGENT_TIMEOUT_SECONDS)


def agent_deadline_seconds() -> float:
    return _positive_float("SMART_HOME_AGENT_DEADLINE", DEFAULT_AGENT_DEADLINE_SECONDS)


def agent_max_tool_rounds() -> int:
    raw = os.environ.get("SMART_HOME_AGENT_MAX_TOOL_ROUNDS", "")
    if raw.strip().isdigit() and int(raw.strip()) > 0:
        return int(raw.strip())
    return DEFAULT_AGENT_MAX_TOOL_ROUNDS


def home_service_url() -> str:
    return os.environ.get("SMART_HOME_SERVICE_URL", DEFAULT_HOME_SERVICE_URL).strip()


def _positive_float(name: str, fallback: float) -> float:
    raw = os.environ.get(name, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback
