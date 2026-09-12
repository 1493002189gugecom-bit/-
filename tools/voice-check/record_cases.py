"""Record Phase A ASR/KWS cases from the physical Realtek microphone.

The script explicitly selects a Realtek input by name and never changes the
Windows default device. Press Enter to record each case; audio is written as
16 kHz mono PCM16 WAV. Audio files are globally ignored by git.

Examples:
  python tools/voice-check/record_cases.py --cases tools/voice-check/cases/asr-30.tsv
  python tools/voice-check/record_cases.py --phrases tools/voice-check/cases/wake-20.txt \
      --out-dir tools/voice-check/cases/audio/wake
"""
from __future__ import annotations

import argparse
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


def list_usable_inputs() -> int:
    """Print input devices that can open as mono float32 at 16 kHz."""
    import sounddevice as sd

    hostapis = sd.query_hostapis()
    print("可用输入设备（支持 16 kHz 单声道）：")
    for index, device in enumerate(sd.query_devices()):
        if int(device["max_input_channels"]) <= 0:
            continue
        try:
            sd.check_input_settings(device=index, channels=1, samplerate=config.SAMPLE_RATE, dtype="float32")
        except sd.PortAudioError:
            continue
        host = str(hostapis[int(device["hostapi"])]["name"])
        print(f"  #{index:>2} [{host}] {device['name']}")
    print()
    print("当前优先列表（SMART_HOME_INPUT_DEVICE 可覆盖）：" + ", ".join(config.input_device_candidates()))
    try:
        chosen = audio_utils.select_input_device(None, config.SAMPLE_RATE)
        print(f"实际将使用：#{chosen.index} {chosen.name} [{chosen.hostapi}]")
    except RuntimeError as exc:
        print(f"当前无法选定输入设备：{exc}")
        return 2
    return 0


def load_tsv(path: Path) -> list[dict]:
    cases = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise ValueError(f"{path}:{lineno}: expected id<TAB>wav[<TAB>expected]")
        wav = Path(parts[1].strip())
        # Optional fourth field is the exact phrase to read; the third field is
        # reserved for ASR key-information tokens.
        prompt = parts[3].strip() if len(parts) > 3 else (parts[2].strip() if len(parts) > 2 else parts[0].strip())
        cases.append({"id": parts[0].strip(), "wav": wav, "prompt": prompt})
    return cases


def load_phrases(path: Path, out_dir: Path) -> list[dict]:
    rows = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        rows.append({"id": f"{lineno:03d}", "wav": out_dir / f"{lineno:03d}.wav", "prompt": text})
    return rows


def record(device_index: int, seconds: float) -> np.ndarray:
    frames = int(seconds * config.SAMPLE_RATE)
    audio = sd.rec(
        frames,
        samplerate=config.SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=device_index,
        blocking=True,
    )[:, 0]
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 1.0:
        audio = audio / peak
    return audio


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--cases", type=Path, help="TSV: id, wav path, expected words")
    source.add_argument("--phrases", type=Path, help="one phrase per line")
    parser.add_argument("--out-dir", type=Path, default=Path("tools/voice-check/cases/audio"))
    parser.add_argument("--device-contains", default=None, help="name filter; default uses the configured preference list")
    parser.add_argument("--list-devices", action="store_true", help="print usable inputs and exit")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--start", type=int, default=1, help="1-based first case")
    parser.add_argument("--force", action="store_true", help="overwrite existing WAV files")
    parser.add_argument("--auto", action="store_true", help="record consecutively without Enter prompts")
    parser.add_argument("--check-level", action="store_true", help="measure one second and warn if the input looks silent")
    args = parser.parse_args()

    if args.list_devices:
        return list_usable_inputs()
    if not args.cases and not args.phrases:
        parser.error("one of --cases or --phrases is required")

    device = audio_utils.select_input_device(args.device_contains, config.SAMPLE_RATE)
    print(f"Input: #{device.index} {device.name} [{device.hostapi}]")
    print(f"Format: {config.SAMPLE_RATE} Hz, mono, PCM16; duration: {args.seconds:.1f}s")

    if args.check_level:
        print("测量 1 秒输入电平，请说话……")
        probe = record(device.index, 1.0)
        probe_peak = float(np.max(np.abs(probe))) if len(probe) else 0.0
        print(f"电平峰值 {probe_peak:.4f}")
        if probe_peak < 0.02:
            print(
                "警告：几乎没有声音。请检查耳机静音键、Windows 输入音量，"
                "并确认选择的是你正在使用的麦克风；未解决前不要开始正式录制。",
                file=sys.stderr,
            )
            return 3

    cases = load_tsv(args.cases) if args.cases else load_phrases(args.phrases, args.out_dir)
    cases = cases[max(0, args.start - 1):]
    if not cases:
        print("no cases to record", file=sys.stderr)
        return 2

    def resolve(wav: Path) -> Path:
        return wav if wav.is_absolute() else Path.cwd() / wav

    pending = [c for c in cases if not resolve(c["wav"]).exists()]
    print()
    print(f"待录 {len(pending)} 条，已存在 {len(cases) - len(pending)} 条")
    if not pending:
        print("全部已录制。若要重录，加 --force；若要续录，用 --start N。")
        return 0
    print("录音时请保持正常语速；输入 s 跳过当前，输入 q 退出。")
    print()

    for position, case in enumerate(cases, args.start):
        wav = resolve(case["wav"])
        wav.parent.mkdir(parents=True, exist_ok=True)
        if wav.exists() and not args.force:
            print(f"[{position}/{len(cases)+args.start-1}] SKIP existing {wav}")
            continue

        print(f"\n[{position}/{len(cases)+args.start-1}] 请朗读：{case['prompt']}")
        if not args.auto:
            answer = input("按 Enter 开始（输入 s 跳过，q 退出）：").strip().lower()
            if answer == "q":
                break
            if answer == "s":
                continue
        print("3...", end=" ", flush=True)
        time.sleep(0.5)
        print("2...", end=" ", flush=True)
        time.sleep(0.5)
        print("1... 开始")
        audio = record(device.index, args.seconds)
        sf.write(str(wav), audio, config.SAMPLE_RATE, subtype="PCM_16")
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        print(f"已保存 {wav}  peak={peak:.4f} rms={rms:.4f}")
        if peak < 0.01:
            print("警告：录音电平很低，请检查麦克风或隐私权限。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
