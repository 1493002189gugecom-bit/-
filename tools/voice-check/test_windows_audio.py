"""Compare Windows-native playback against PortAudio, with a meter reading.

Produces three audible attempts and one WAV file so playback can also be checked
in a normal media player:
  1. winsound.Beep        - system default endpoint, Windows native
  2. winsound.PlaySound   - the same tone written as a WAV file
  3. sounddevice          - the PortAudio path used by the voice service

Run: python tools/voice-check/test_windows_audio.py
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
import wave
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import audio_utils  # noqa: E402

SAMPLE_RATE = 24000


def make_tone(seconds: float, freq: float, volume: float) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE), dtype=np.float32) / SAMPLE_RATE
    tone = (volume * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    fade = int(0.05 * SAMPLE_RATE)
    tone[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    tone[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return tone


def write_wav(path: Path, tone: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(tone, -1.0, 1.0)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes((pcm * 32767).astype("<i2").tobytes())


def play_message_box_tone() -> None:
    """Play the built-in Windows system sound via the default endpoint."""
    import winsound

    winsound.MessageBeep(winsound.MB_ICONASTERISK)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--freq", type=float, default=440.0)
    parser.add_argument("--volume", type=float, default=0.5)
    parser.add_argument("--wav", type=Path, default=Path("tools/voice-check/cases/audio/output-test.wav"))
    args = parser.parse_args()

    tone = make_tone(args.seconds, args.freq, args.volume)
    write_wav(args.wav, tone)
    print(f"已生成测试音文件: {args.wav}")
    print("（你也可以用系统播放器直接打开它来验证耳机是否有声）")
    print()

    import winsound

    print("[1/3] Windows 系统提示音（MessageBeep，走系统默认设备）")
    play_message_box_tone()
    time.sleep(1.2)

    print("[2/3] winsound.PlaySound 播放上面那个 WAV")
    winsound.PlaySound(str(args.wav), winsound.SND_FILENAME)
    time.sleep(1.2)

    print("[3/3] sounddevice（语音服务使用的 PortAudio 路径）")
    import sounddevice as sd

    chosen = audio_utils.select_output_device(None, SAMPLE_RATE)
    print(f"    目标设备: #{chosen.index} {chosen.name} [{chosen.hostapi}]")
    try:
        with sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=chosen.index) as stream:
            stream.write(tone.reshape(-1, 1))
            time.sleep(0.4)
        print("    write 完成")
    except Exception as exc:  # noqa: BLE001
        print(f"    播放失败: {type(exc).__name__}: {exc}")

    print()
    print("请告诉我：1、2、3 三个里面，哪几个听到了声音？")
    print("  - 三个都没听到 -> 耳机输出或系统输出路由问题，与代码无关")
    print("  - 只有 3 没听到   -> PortAudio 路径问题，我改播放实现")
    print("  - 只有 1、2 听到  -> 同上")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
