"""Audition TTS voices so a preferred one can be chosen.

Works with both backends: `--provider edge` (default) auditions the Edge neural
voices, `--provider kokoro` auditions the local Kokoro speaker ids.

Run: python tools/voice-check/audition_voices.py --voices zh-CN-XiaoxiaoNeural,zh-CN-YunyangNeural
"""
from __future__ import annotations

import argparse
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
import config  # noqa: E402
import playback  # noqa: E402
import voice_models  # noqa: E402

# Kokoro v1.1 Chinese voices. Names follow the upstream hexgrad/Kokoro-82M-v1.1-zh
# naming scheme (zf_* female, zm_* male); ids outside this map are shown as-is.
CHINESE_VOICE_NAMES = {
    45: "zf_xiaobei",
    46: "zf_xiaoni",
    47: "zf_xiaoxiao",
    48: "zf_xiaoyi",
    49: "zm_yunjian",
    50: "zm_yunxi",
    51: "zm_yunxia",
    52: "zm_yunyang",
}


def parse_ids(text: str) -> list[int]:
    ids: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            ids.extend(range(int(start), int(end) + 1))
        else:
            ids.append(int(part))
    return ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default=None, help="edge (default) or kokoro")
    parser.add_argument("--voices", default=None, help="edge voice names, comma separated")
    parser.add_argument("--speakers", default="45-52", help="kokoro ids or ranges, e.g. 45-52")
    parser.add_argument("--text", default="已把客厅的空调调到二十六度。")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--out-dir", type=Path, default=Path("docs/superpowers/reports/artifacts/tts-voices"))
    parser.add_argument("--save", action="store_true", help="also write WAV files")
    parser.add_argument("--gap", type=float, default=0.6)
    args = parser.parse_args()

    provider = (args.provider or config.tts_provider()).lower()
    target = audio_utils.select_playback_target()
    print(f"播放目标: {target.describe()}")
    print(f"文本: {args.text}   提供商: {provider}")
    print()

    auditioned = 0
    if provider == "edge":
        names = (
            [v.strip() for v in args.voices.split(",") if v.strip()]
            if args.voices
            else list(config.EDGE_VOICE_CANDIDATES)
        )
        engine = voice_models.create_tts("edge")
        for voice in names:
            try:
                samples, rate = voice_models.TtsEngine("edge", voice).synthesize(args.text)
            except Exception as exc:  # noqa: BLE001
                print(f"{voice:<28} 合成失败: {type(exc).__name__}: {exc}")
                continue
            print(f"{voice:<28} 时长 {len(samples) / rate:.2f}s  正在播放……")
            if args.save:
                args.out_dir.mkdir(parents=True, exist_ok=True)
                sf.write(str(args.out_dir / f"edge-{voice}.wav"), samples, rate, subtype="PCM_16")
            playback.play(samples, rate, target)
            time.sleep(args.gap)
            auditioned += 1
        del engine
    else:
        ids = parse_ids(args.speakers)
        if not ids:
            print("no speaker ids given", file=sys.stderr)
            return 2
        engine = voice_models.create_tts("kokoro")
        total = engine._kokoro_engine().num_speakers
        print(f"模型音色总数: {total}")
        for sid in ids:
            if sid >= total:
                print(f"sid={sid} 超出范围（0-{total - 1}），跳过")
                continue
            name = CHINESE_VOICE_NAMES.get(sid, "?")
            try:
                samples, rate = voice_models.synthesize(engine, args.text, sid, args.speed)
            except Exception as exc:  # noqa: BLE001
                print(f"sid={sid:>3} {name:<14} 合成失败: {type(exc).__name__}: {exc}")
                continue
            print(f"sid={sid:>3} {name:<14} 时长 {len(samples) / rate:.2f}s  正在播放……")
            if args.save:
                args.out_dir.mkdir(parents=True, exist_ok=True)
                sf.write(
                    str(args.out_dir / f"voice-{sid:03d}-{name}.wav"),
                    samples,
                    rate,
                    subtype="PCM_16",
                )
            playback.play(samples, rate, target)
            time.sleep(args.gap)
            auditioned += 1

    if auditioned == 0:
        print("\n没有成功合成任何音色。")
        return 1
    print()
    print("选定后设置环境变量，例如：")
    print("  SMART_HOME_TTS_VOICE=zh-CN-YunyangNeural     (edge)")
    print("  SMART_HOME_TTS_SPEAKER=48                    (kokoro)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
