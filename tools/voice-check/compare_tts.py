"""Compare TTS options for home announcements, side by side.

Options covered:
  kokoro      - current local model (sherpa-onnx, 82M)
  zipvoice    - local zero-shot voice cloning (sherpa-onnx)
  edge        - Microsoft Edge online neural voices (edge-tts)

Outputs WAV files into one directory and plays them in sequence so the voice
quality can be judged directly.

Run: python tools/voice-check/compare_tts.py --options kokoro,edge
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import audio_utils  # noqa: E402
import playback  # noqa: E402
import voice_models  # noqa: E402

TEXT = "已把客厅的空调调到二十六度，卧室的灯也关上了。"

# Edge neural voices worth auditioning for Chinese home announcements.
EDGE_VOICES = [
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-XiaoyiNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunyangNeural",
]


def kokoro(text: str, out_dir: Path, speaker: int) -> list[tuple[str, Path, float]]:
    engine = voice_models.create_tts("kokoro")
    t0 = time.perf_counter()
    samples, rate = voice_models.synthesize(engine, text, speaker)
    elapsed = time.perf_counter() - t0
    out = out_dir / f"kokoro-{speaker}.wav"
    sf.write(str(out), samples, rate, subtype="PCM_16")
    return [(f"kokoro sid={speaker} ({elapsed:.2f}s)", out, elapsed)]


def edge(text: str, out_dir: Path) -> list[tuple[str, Path, float]]:
    import edge_tts

    results = []
    for voice in EDGE_VOICES:
        out = out_dir / f"edge-{voice}.wav"
        t0 = time.perf_counter()
        try:
            asyncio.run(_edge_one(text, voice, out))
            elapsed = time.perf_counter() - t0
            results.append((f"edge {voice} ({elapsed:.2f}s)", out, elapsed))
        except Exception as exc:  # noqa: BLE001
            print(f"  edge {voice} 失败: {type(exc).__name__}: {exc}")
    return results


async def _edge_one(text: str, voice: str, out: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    with open(out, "wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])


def zipvoice(text: str, out_dir: Path, reference: Path, reference_text: str, steps: int) -> list[tuple[str, Path, float]]:
    """Local zero-shot cloning; requires the ZipVoice model and vocoder."""
    import config

    root = config.models_dir() / "sherpa-onnx-zipvoice-distill-int8-zh-en-emilia"
    vocoder = config.models_dir() / "vocos_24khz.onnx"
    if not root.exists() or not vocoder.exists():
        print("  ZipVoice 模型缺失，跳过")
        return []
    if not reference.exists():
        print(f"  参考音频缺失: {reference}")
        return []

    import sherpa_onnx

    t0 = time.perf_counter()
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            zipvoice=sherpa_onnx.OfflineTtsZipvoiceModelConfig(
                encoder=str(root / "encoder.int8.onnx"),
                decoder=str(root / "decoder.int8.onnx"),
                vocoder=str(vocoder),
                tokens=str(root / "tokens.txt"),
                lexicon=str(root / "lexicon.txt"),
                data_dir=str(root / "espeak-ng-data"),
                feat_scale=0.1,
                t_shift=0.5,
                target_rms=0.1,
                guidance_scale=1.0,
            ),
            num_threads=2,
            provider="cpu",
            debug=False,
        ),
    )
    if not cfg.validate():
        print("  ZipVoice 配置无效")
        return []
    tts = sherpa_onnx.OfflineTts(cfg)

    # ZipVoice takes the reference waveform directly: (text, prompt_text,
    # prompt_samples, sample_rate, speed, num_steps).
    prompt, prompt_rate = sf.read(str(reference), dtype="float32", always_2d=False)
    if prompt.ndim > 1:
        prompt = prompt.mean(axis=1)
    prompt = np.asarray(prompt, dtype=np.float32).reshape(-1)
    audio = tts.generate(
        text, reference_text, prompt, int(prompt_rate), 1.0, steps
    )
    elapsed = time.perf_counter() - t0
    if audio is None or len(audio.samples) == 0:
        print("  ZipVoice 未生成音频")
        return []
    out = out_dir / "zipvoice-clone.wav"
    samples = np.asarray(audio.samples, dtype=np.float32)
    sf.write(str(out), samples, audio.sample_rate, subtype="PCM_16")
    return [(f"zipvoice clone ({elapsed:.2f}s)", out, elapsed)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--options", default="kokoro,edge")
    parser.add_argument("--text", default=TEXT)
    parser.add_argument("--speaker", type=int, default=47)
    parser.add_argument("--reference", type=Path, default=None, help="reference WAV for ZipVoice")
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--num-steps", type=int, default=4)
    parser.add_argument("--out-dir", type=Path, default=Path("docs/superpowers/reports/artifacts/tts-compare"))
    parser.add_argument("--no-play", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    wanted = [x.strip() for x in args.options.split(",") if x.strip()]

    target = None if args.no_play else audio_utils.select_playback_target()
    if target:
        print(f"播放目标: {target.describe()}")
    print(f"文本: {args.text}")
    print()

    produced: list[tuple[str, Path, float]] = []
    for option in wanted:
        print(f"--- {option} ---")
        if option == "kokoro":
            produced += kokoro(args.text, args.out_dir, args.speaker)
        elif option == "edge":
            produced += edge(args.text, args.out_dir)
        elif option == "zipvoice":
            if not args.reference:
                print("  需要 --reference 指定参考音频")
            else:
                produced += zipvoice(
                    args.text, args.out_dir, args.reference, args.reference_text, args.num_steps
                )
        else:
            print(f"  未知选项: {option}")

    print()
    print(f"共生成 {len(produced)} 个文件:")
    for label, path, elapsed in produced:
        print(f"  {label:<42} {path.name}")

    if target and not args.no_play:
        print()
        for label, path, _ in produced:
            print(f"播放 {label} ……")
            samples, rate = sf.read(str(path), dtype="float32", always_2d=False)
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            playback.play(np.asarray(samples, dtype=np.float32), rate, target)
            time.sleep(0.5)

    print()
    print(f"全部 WAV 在: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
