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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases", type=Path, help="TSV: id, wav path, expected words")
    source.add_argument("--phrases", type=Path, help="one phrase per line")
    parser.add_argument("--out-dir", type=Path, default=Path("tools/voice-check/cases/audio"))
    parser.add_argument("--device-contains", default=config.DEFAULT_INPUT_DEVICE)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--start", type=int, default=1, help="1-based first case")
    parser.add_argument("--force", action="store_true", help="overwrite existing WAV files")
    parser.add_argument("--auto", action="store_true", help="record consecutively without Enter prompts")
    args = parser.parse_args()

    device = audio_utils.select_input_device(args.device_contains, config.SAMPLE_RATE)
    print(f"Input: #{device.index} {device.name} [{device.hostapi}]")
    print(f"Format: {config.SAMPLE_RATE} Hz, mono, PCM16; duration: {args.seconds:.1f}s")

    cases = load_tsv(args.cases) if args.cases else load_phrases(args.phrases, args.out_dir)
    cases = cases[max(0, args.start - 1):]
    if not cases:
        print("no cases to record", file=sys.stderr)
        return 2

    for position, case in enumerate(cases, args.start):
        wav = case["wav"]
        if not wav.is_absolute():
            wav = Path.cwd() / wav
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
