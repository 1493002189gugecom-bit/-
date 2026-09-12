"""Thin CPU-only wrappers around sherpa-onnx voice models."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import sherpa_onnx

import config


def create_asr() -> sherpa_onnx.OfflineRecognizer:
    paths = config.asr_paths()
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(paths["model"]),
        tokens=str(paths["tokens"]),
        num_threads=2,
        use_itn=True,
        language="zh",
        provider="cpu",
        debug=False,
    )


def transcribe(recognizer: sherpa_onnx.OfflineRecognizer, samples: np.ndarray, sample_rate: int = 16000) -> str:
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate, np.asarray(samples, dtype=np.float32))
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


def create_tts() -> sherpa_onnx.OfflineTts:
    paths = config.tts_paths()
    kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
        model=str(paths["model"]),
        voices=str(paths["voices"]),
        tokens=str(paths["tokens"]),
        data_dir=str(paths["data_dir"]),
        lexicon=paths["lexicon"],
    )
    model = sherpa_onnx.OfflineTtsModelConfig(
        kokoro=kokoro,
        num_threads=2,
        provider="cpu",
        debug=False,
    )
    tts_config = sherpa_onnx.OfflineTtsConfig(model=model, max_num_sentences=1)
    if not tts_config.validate():
        raise RuntimeError("invalid Kokoro TTS configuration")
    return sherpa_onnx.OfflineTts(tts_config)


def synthesize(tts: sherpa_onnx.OfflineTts, text: str, speaker_id: int = 47) -> tuple[np.ndarray, int]:
    audio = tts.generate(text, sid=speaker_id, speed=1.0)
    if audio is None or len(audio.samples) == 0:
        raise RuntimeError("TTS generated no samples")
    return np.asarray(audio.samples, dtype=np.float32), int(audio.sample_rate)


def create_vad() -> sherpa_onnx.VadModel:
    silero = sherpa_onnx.SileroVadModelConfig(
        model=str(config.vad_model()),
        threshold=0.5,
        min_silence_duration=0.6,
        min_speech_duration=0.25,
        window_size=512,
        max_speech_duration=20,
    )
    vad_config = sherpa_onnx.VadModelConfig(
        silero_vad=silero,
        sample_rate=config.SAMPLE_RATE,
        num_threads=1,
        provider="cpu",
        debug=False,
    )
    if not vad_config.validate():
        raise RuntimeError("invalid Silero VAD configuration")
    return sherpa_onnx.VadModel.create(vad_config)


def create_kws(keywords_file: Path) -> sherpa_onnx.KeywordSpotter:
    paths = config.kws_paths()
    return sherpa_onnx.KeywordSpotter(
        tokens=str(paths["tokens"]),
        encoder=str(paths["encoder"]),
        decoder=str(paths["decoder"]),
        joiner=str(paths["joiner"]),
        keywords_file=str(keywords_file),
        num_threads=2,
        provider="cpu",
        keywords_score=2.0,
        keywords_threshold=0.25,
        num_trailing_blanks=1,
    )
