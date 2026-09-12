"""Verify speaker output: endpoint volume, stream open, and an audible tone.

The Phase A loop previously only ever ran with --no-tts, so playback had never
actually been verified. This script isolates the output path.

Run: python tools/voice-check/test_output.py
"""
from __future__ import annotations

import argparse
import sys
import time
import winreg
from pathlib import Path

import numpy as np
import sounddevice as sd

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "voice-service" / "src"))
import audio_utils  # noqa: E402
import config  # noqa: E402

RENDER_ROOT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
PKEY_DEVICE_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
PKEY_DEVICE_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"


def endpoint_volumes(filters: list[str]) -> None:
    print("=== Windows 输出端点音量（只读）===")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, RENDER_ROOT) as root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                try:
                    subkey = winreg.EnumKey(root, index)
                except OSError:
                    continue
                try:
                    with winreg.OpenKey(root, subkey) as key:
                        values = {}
                        for i in range(winreg.QueryInfoKey(key)[1]):
                            name, value, _ = winreg.EnumValue(key, i)
                            values[name] = value
                        props = {}
                        try:
                            with winreg.OpenKey(key, "Properties") as prop_key:
                                for i in range(winreg.QueryInfoKey(prop_key)[1]):
                                    name, value, _ = winreg.EnumValue(prop_key, i)
                                    props[name] = value
                        except FileNotFoundError:
                            pass
                except OSError:
                    continue

                desc = str(props.get(PKEY_DEVICE_DESC) or "")
                name = str(props.get(PKEY_DEVICE_NAME) or "")
                label = f"{name} / {desc}"
                haystack = f"{name} {desc}".casefold()
                if not any(f.casefold() in haystack for f in filters):
                    continue
                state = values.get("DeviceState")
                levels = {k: v for k, v in values.items() if k.startswith("Level:")}
                active = "" if state is None else ("ACTIVE" if int(state) & 0xFF == 1 else f"state={int(state)}")
                print(f"  {label}  {active}")
                for key_name in sorted(levels):
                    pct = levels[key_name]
                    print(f"      {key_name}: {pct}{'  <-- 静音/0%!' if pct == 0 else ''}")
    except FileNotFoundError:
        print("  (无法读取 Render 注册表)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--freq", type=float, default=440.0)
    parser.add_argument("--volume", type=float, default=0.4)
    parser.add_argument("--loop", type=int, default=1, help="play the tone N times with pauses")
    parser.add_argument("--gap", type=float, default=1.2, help="silence between attempts")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="try every matching output host API instead of only the preferred one",
    )
    args = parser.parse_args()

    print("=== PortAudio 输出设备（支持 24 kHz 单声道）===")
    hostapis = sd.query_hostapis()
    for index, device in enumerate(sd.query_devices()):
        if int(device["max_output_channels"]) <= 0:
            continue
        try:
            sd.check_output_settings(device=index, channels=1, samplerate=24000, dtype="float32")
            ok = "mono24k=OK"
        except sd.PortAudioError:
            ok = "mono24k=no"
        print(f"  #{index:>2} [{hostapis[int(device['hostapi'])]['name']}] {device['name']}  {ok}")

    endpoint_volumes([config.DEFAULT_OUTPUT_DEVICE, "Realtek"])

    chosen = audio_utils.select_output_device(None, 24000)
    print()
    print(f"=== 首选输出: #{chosen.index} {chosen.name} [{chosen.hostapi}] ===")

    t = np.arange(int(args.seconds * 24000), dtype=np.float32) / 24000
    # Fade in/out so the tone is clean and obviously artificial.
    tone = (args.volume * np.sin(2 * np.pi * args.freq * t)).astype(np.float32)
    fade = int(0.05 * 24000)
    tone[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    tone[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    print(f"生成 {len(tone)} 采样（{args.seconds:g}s），峰值 {float(np.max(np.abs(tone))):.3f}")
    print()

    targets = [chosen]
    if args.sweep:
        seen = {chosen.index}
        for device in audio_utils.list_output_devices():
            if device.index in seen:
                continue
            if not any(p.casefold() in device.name.casefold() for p in config.output_device_candidates()):
                continue
            try:
                sd.check_output_settings(device=device.index, channels=1, samplerate=24000, dtype="float32")
            except sd.PortAudioError:
                continue
            seen.add(device.index)
            targets.append(device)

    for target in targets:
        print(f"=== #{target.index} {target.name} [{target.hostapi}] ===")
        for attempt in range(1, args.loop + 1):
            print(f"  [{attempt}/{args.loop}] 播放中……请听耳机")
            try:
                with sd.OutputStream(
                    samplerate=24000, channels=1, dtype="float32", device=target.index
                ) as stream:
                    print(
                        f"      流参数 samplerate={stream.samplerate} channels={stream.channels} "
                        f"latency={stream.latency}"
                    )
                    stream.write(tone.reshape(-1, 1))
                    # DirectSound buffers can still hold audio; give the device
                    # time to drain before the stream closes.
                    time.sleep(0.4)
                    print("      write 完成")
            except Exception as exc:  # noqa: BLE001
                print(f"      播放失败: {type(exc).__name__}: {exc}")
                break
            time.sleep(args.gap)
        print()

    print("如果完全没听到：")
    print("  1) Windows 右下角音量合成器里，Python/终端 的音量是否被单独调低或静音")
    print("  2) 耳机线控/耳罩上的音量旋钮是否拧到最小")
    print("  3) 上面的端点 Level 是否为 0")
    print("  4) 耳机是否插在“仅输出”接口而非耳机口")
    print("  5) 是否启用了“空间音效/虚拟环绕”导致输出被路由到别处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
