"""Capture speaker->air->microphone playback for A8 self-trigger testing.

It plays the same fixed reply used by loop.py ("收到。") through the physical
Realtek output while recording the physical Realtek microphone. The recordings
are then evaluated by check_wake.py with both KWS and ASR.
"""
from __future__ import annotations

import argparse
import queue
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import audio_utils  # noqa: E402
import config  # noqa: E402
import voice_models  # noqa: E402
from loop import play  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("tools/voice-check/cases/self-trigger"))
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--text", default="收到。")
    parser.add_argument("--speaker-id", type=int, default=47)
    parser.add_argument("--input-contains", default=config.DEFAULT_INPUT_DEVICE)
    parser.add_argument("--output-contains", default=config.DEFAULT_OUTPUT_DEVICE)
    parser.add_argument("--yes", action="store_true", help="skip the audible-playback confirmation")
    args = parser.parse_args()

    if args.count < 1:
        raise ValueError("--count must be >= 1")
    input_device = audio_utils.select_input_device(args.input_contains, config.SAMPLE_RATE)
    output_device = audio_utils.select_output_device(args.output_contains, 24000)
    print(f"Input : #{input_device.index} {input_device.name} [{input_device.hostapi}]")
    print(f"Output: #{output_device.index} {output_device.name} [{output_device.hostapi}]")
    print(f"将正常音量播放 {args.count} 次：{args.text}")
    if not args.yes and input("按 Enter 继续，输入 q 取消：").strip().lower() == "q":
        return 2

    tts = voice_models.create_tts()
    reply, reply_sr = voice_models.synthesize(tts, args.text, args.speaker_id)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for index in range(1, args.count + 1):
        blocks: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status):  # noqa: ANN001
            if status:
                print(f"audio status: {status}", file=sys.stderr)
            blocks.put(np.asarray(indata[:, 0], dtype=np.float32).copy())

        with sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            blocksize=512,
            device=input_device.index,
            channels=1,
            dtype="float32",
            callback=callback,
        ):
            time.sleep(0.5)
            play(reply, reply_sr, output_device.index)
            time.sleep(1.0)

        collected: list[np.ndarray] = []
        while not blocks.empty():
            collected.append(blocks.get_nowait())
        audio = np.concatenate(collected) if collected else np.empty(0, dtype=np.float32)
        out = args.out_dir / f"playback-{index:02d}.wav"
        sf.write(str(out), audio, config.SAMPLE_RATE, subtype="PCM_16")
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        print(f"[{index}/{args.count}] {out} duration={len(audio)/config.SAMPLE_RATE:.2f}s peak={peak:.4f} rms={rms:.4f}")
        if peak < 0.01:
            print("警告：回录电平很低，结果不可用于声学回环验收。")

    print("下一步运行 check_wake.py；其会同时检查 KWS 和 ASR 禁止词。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
